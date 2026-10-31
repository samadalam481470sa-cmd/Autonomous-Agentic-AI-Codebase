//! Local-only bounded OpenAI-compatible inference gateway for llama.cpp.
//! The gateway is a proxy, not a GPU inference engine. Never expose it publicly.
use axum::{
    body::Body,
    extract::State,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::{env, net::{IpAddr, SocketAddr}, sync::Arc, time::Duration};
use tokio::sync::Semaphore;

#[derive(Clone)]
struct Gateway {
    client: reqwest::Client,
    upstream: String,
    max_output: u64,
    gate: Arc<Semaphore>,
}

fn parse_upstream(raw: &str) -> Result<String, String> {
    let url = reqwest::Url::parse(raw).map_err(|_| "Invalid upstream URL")?;
    if url.scheme() != "http"
        || url.username() != ""
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/v1"
    {
        return Err("Upstream must be a plain loopback http://.../v1 URL".into());
    }
    let host = url.host_str().ok_or("Missing upstream host")?;
    if !matches!(host, "localhost" | "127.0.0.1" | "[::1]") {
        return Err("Only loopback model servers are supported".into());
    }
    Ok(raw.trim_end_matches('/').to_string())
}

fn sanitize(mut value: Value, max_output: u64) -> Result<Value, String> {
    if serde_json::to_vec(&value).map_err(|e| e.to_string())?.len() > 256_000 {
        return Err("Request exceeds 256 KB".into());
    }
    let obj = value.as_object_mut().ok_or("Expected JSON object")?;
    let messages = obj
        .get("messages")
        .and_then(Value::as_array)
        .ok_or("messages must be an array")?;
    if messages.is_empty() || messages.len() > 40 {
        return Err("Message count out of range".into());
    }
    let streaming = match obj.get("stream") {
        None | Some(Value::Bool(false)) => false,
        Some(Value::Bool(true)) => true,
        _ => return Err("stream must be a boolean".into()),
    };
    obj.insert("stream".into(), Value::Bool(streaming));
    let asked = obj.get("max_tokens").and_then(Value::as_u64).unwrap_or(max_output);
    obj.insert("max_tokens".into(), json!(asked.clamp(1, max_output)));
    Ok(value)
}

async fn health() -> Json<Value> {
    Json(json!({"status":"ok","engine":"rust-gateway","inference":"external-local"}))
}

async fn models(State(g): State<Gateway>) -> Result<Json<Value>, (StatusCode, String)> {
    let response = g.client.get(format!("{}/models", g.upstream)).send().await
        .map_err(|_| (StatusCode::BAD_GATEWAY, "Local model unavailable".into()))?;
    if !response.status().is_success() {
        return Err((StatusCode::BAD_GATEWAY, "Local model returned an error".into()));
    }
    let data = response.json::<Value>().await
        .map_err(|_| (StatusCode::BAD_GATEWAY, "Invalid model response".into()))?;
    Ok(Json(data))
}

async fn chat(State(g): State<Gateway>, Json(body): Json<Value>)
    -> Result<Response, (StatusCode, String)>
{
    let body = sanitize(body, g.max_output)
        .map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    let streaming = body["stream"].as_bool().unwrap_or(false);

    // Own the permit in a streaming response. Releasing it when HTTP headers
    // arrive would allow unbounded simultaneous model generations.
    let permit = g.gate.clone().acquire_owned().await
        .map_err(|_| (StatusCode::SERVICE_UNAVAILABLE, "Gateway shutting down".into()))?;
    let response = g.client.post(format!("{}/chat/completions", g.upstream))
        .json(&body)
        .send()
        .await
        .map_err(|_| (StatusCode::BAD_GATEWAY, "Local model unavailable or timed out".into()))?;
    if !response.status().is_success() {
        return Err((StatusCode::BAD_GATEWAY, "Local inference failed".into()));
    }

    if streaming {
        // Do not disguise an upstream JSON/error body as an SSE stream.
        let content_type = response.headers().get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok()).unwrap_or("").to_ascii_lowercase();
        if !content_type.starts_with("text/event-stream") {
            return Err((StatusCode::BAD_GATEWAY, "Local model did not return an SSE stream".into()));
        }
        // Pass chunks through without buffering the entire answer. The owned
        // permit remains in the stream until completion or client disconnect.
        let chunks = response.bytes_stream().map(move |chunk| {
            let _hold_permit = &permit;
            chunk
        });
        return Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "text/event-stream; charset=utf-8")
            .header(header::CACHE_CONTROL, "no-cache")
            .header("x-accel-buffering", "no")
            .body(Body::from_stream(chunks))
            .map_err(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Cannot create stream".into()));
    }

    let data = response.json::<Value>().await
        .map_err(|_| (StatusCode::BAD_GATEWAY, "Invalid model JSON".into()))?;
    Ok(Json(data).into_response())
}

pub async fn serve() -> Result<(), Box<dyn std::error::Error>> {
    let upstream = parse_upstream(&env::var("LLAMA_UPSTREAM")
        .unwrap_or_else(|_| "http://127.0.0.1:9931/v1".into()))?;
    let max_output = env::var("RUST_MAX_OUTPUT_TOKENS").ok()
        .and_then(|x| x.parse::<u64>().ok()).unwrap_or(1024).clamp(64, 8192);
    let parallel = env::var("RUST_MAX_CONCURRENT").ok()
        .and_then(|x| x.parse::<usize>().ok()).unwrap_or(1).clamp(1, 4);
    let port = env::var("RUST_GATEWAY_PORT").ok()
        .and_then(|x| x.parse::<u16>().ok()).unwrap_or(8088);
    let client = reqwest::Client::builder().timeout(Duration::from_secs(180))
        .no_proxy().build()?;
    let state = Gateway { client, upstream, max_output, gate: Arc::new(Semaphore::new(parallel)) };
    let app = Router::new()
        .route("/health", get(health))
        .route("/v1/models", get(models))
        .route("/v1/chat/completions", post(chat))
        .with_state(state);
    let address = SocketAddr::new(IpAddr::V4(std::net::Ipv4Addr::LOCALHOST), port);
    let listener = tokio::net::TcpListener::bind(address).await?;
    println!("Rust local inference gateway on {address}");
    axum::serve(listener, app).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::to_bytes;

    #[test]
    fn rejects_remote_servers() {
        for s in [
            "https://api.example.com/v1",
            "http://example.com/v1",
            "http://127.0.0.1.evil.com/v1",
            "http://user:pass@localhost:9931/v1",
        ] {
            assert!(parse_upstream(s).is_err());
        }
        assert!(parse_upstream("http://127.0.0.1:9931/v1").is_ok());
    }

    #[test]
    fn validates_stream_flag_and_caps_generation() {
        let input = json!({
            "model": "local", "messages": [{"role":"user","content":"hello"}],
            "max_tokens": 999999, "stream": true
        });
        let output = sanitize(input, 512).unwrap();
        assert_eq!(output["max_tokens"], 512);
        assert_eq!(output["stream"], true);
        assert_eq!(sanitize(json!({"messages":[{}]}), 512).unwrap()["stream"], false);
        assert!(sanitize(json!({"messages":[{}],"stream":"yes"}), 512).is_err());
        assert!(sanitize(json!({"messages":[]}), 512).is_err());
    }

    async fn mock_gateway(content_type: &'static str) -> (Gateway, tokio::task::JoinHandle<()>) {
        let app = Router::new().route("/v1/chat/completions", post(
            move |Json(request): Json<Value>| async move {
                assert_eq!(request["stream"], true);
                assert_eq!(request["max_tokens"], 24);
                (
                    [(header::CONTENT_TYPE, content_type)],
                    "data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"}}]}\n\ndata: [DONE]\n\n",
                )
            }
        ));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });
        let g = Gateway {
            client: reqwest::Client::builder().no_proxy().build().unwrap(),
            upstream: format!("http://127.0.0.1:{port}/v1"),
            max_output: 24,
            gate: Arc::new(Semaphore::new(1)),
        };
        (g, handle)
    }

    #[tokio::test]
    async fn forwards_sse_and_holds_permit_until_body_is_consumed() {
        let (g, server) = mock_gateway("text/event-stream").await;
        let response = chat(State(g.clone()), Json(json!({
            "model":"local", "messages":[{"role":"user","content":"hi"}],
            "stream":true, "max_tokens":900
        }))).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "text/event-stream; charset=utf-8");
        assert_eq!(g.gate.available_permits(), 0);
        let bytes = to_bytes(response.into_body(), 10000).await.unwrap();
        assert!(String::from_utf8_lossy(&bytes).contains("data: [DONE]"));
        assert_eq!(g.gate.available_permits(), 1);
        server.abort();
    }

    #[tokio::test]
    async fn rejects_non_sse_body_before_forwarding_headers() {
        let (g, server) = mock_gateway("application/json").await;
        let err = chat(State(g.clone()), Json(json!({
            "messages":[{"role":"user","content":"hi"}], "stream":true
        }))).await.unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);
        assert_eq!(g.gate.available_permits(), 1);
        server.abort();
    }
}
