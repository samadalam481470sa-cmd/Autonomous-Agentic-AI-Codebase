//! Local-only bounded inference gateway for llama.cpp / Ollama.
//! Binds loopback only; accepts requests only from the local Python backend.
//! It does not load model weights itself or guarantee GPU acceleration.
use axum::{extract::State,http::StatusCode,routing::{get,post},Json,Router};
use serde_json::{json,Value};
use std::{env,net::{IpAddr,SocketAddr},sync::Arc,time::Duration};
use tokio::sync::Semaphore;

#[derive(Clone)]
struct Gateway {
    client:reqwest::Client,
    upstream:String,
    max_output:u64,
    gate:Arc<Semaphore>,
}
fn parse_upstream(raw:&str)->Result<String,String>{
    let url=reqwest::Url::parse(raw).map_err(|_|"Invalid upstream URL")?;
    if url.scheme()!="http" || url.username()!="" || url.password().is_some() ||
        url.query().is_some() || url.fragment().is_some() || url.path()!="/v1" {
        return Err("Upstream must be a plain loopback http://.../v1 URL".into());
    }
    let host=url.host_str().ok_or("Missing upstream host")?;
    if !matches!(host,"localhost"|"127.0.0.1"|"[::1]"){
        return Err("Only loopback model servers are supported".into());
    }
    Ok(raw.trim_end_matches('/').to_string())
}
fn sanitize(mut value:Value,max_output:u64)->Result<Value,String>{
    let obj=value.as_object_mut().ok_or("Expected JSON object")?;
    let messages=obj.get("messages").and_then(Value::as_array).ok_or("messages must be an array")?;
    if messages.is_empty() || messages.len()>40{return Err("Message count out of range".into());}
    if serde_json::to_vec(&value).map_err(|e|e.to_string())?.len()>256_000 {
        return Err("Request exceeds 256 KB".into());
    }
    obj.insert("stream".into(),Value::Bool(false));
    let asked=obj.get("max_tokens").and_then(Value::as_u64).unwrap_or(max_output);
    obj.insert("max_tokens".into(),json!(asked.clamp(1,max_output)));
    Ok(value)
}
async fn health()->Json<Value>{Json(json!({"status":"ok","engine":"rust-gateway","inference":"external-local"}))}
async fn models(State(g):State<Gateway>)->Result<Json<Value>,(StatusCode,String)>{
    let r=g.client.get(format!("{}/models",g.upstream)).send().await
        .map_err(|_|(StatusCode::BAD_GATEWAY,"Local model unavailable".into()))?;
    let status=r.status();
    let data=r.json::<Value>().await.map_err(|_|(StatusCode::BAD_GATEWAY,"Invalid model response".into()))?;
    if !status.is_success(){return Err((StatusCode::BAD_GATEWAY,"Local model returned an error".into()));}
    Ok(Json(data))
}
async fn chat(State(g):State<Gateway>,Json(body):Json<Value>)->Result<Json<Value>,(StatusCode,String)>{
    let body=sanitize(body,g.max_output).map_err(|e|(StatusCode::BAD_REQUEST,e))?;
    let _permit=g.gate.acquire().await.map_err(|_|(StatusCode::SERVICE_UNAVAILABLE,"Gateway shutting down".into()))?;
    let response=g.client.post(format!("{}/chat/completions",g.upstream))
        .json(&body).send().await.map_err(|_|(StatusCode::BAD_GATEWAY,"Local model unavailable or timed out".into()))?;
    if !response.status().is_success(){return Err((StatusCode::BAD_GATEWAY,"Local inference failed".into()));}
    let data=response.json::<Value>().await.map_err(|_|(StatusCode::BAD_GATEWAY,"Invalid model JSON".into()))?;
    Ok(Json(data))
}
pub async fn serve()->Result<(),Box<dyn std::error::Error>>{
    let upstream=parse_upstream(&env::var("LLAMA_UPSTREAM").unwrap_or_else(|_|"http://127.0.0.1:9931/v1".into()))?;
    let max_output=env::var("RUST_MAX_OUTPUT_TOKENS").ok().and_then(|x|x.parse::<u64>().ok()).unwrap_or(1024).clamp(64,8192);
    let parallel=env::var("RUST_MAX_CONCURRENT").ok().and_then(|x|x.parse::<usize>().ok()).unwrap_or(1).clamp(1,4);
    let port=env::var("RUST_GATEWAY_PORT").ok().and_then(|x|x.parse::<u16>().ok()).unwrap_or(8088);
    let client=reqwest::Client::builder().timeout(Duration::from_secs(180)).no_proxy().build()?;
    let state=Gateway{client,upstream,max_output,gate:Arc::new(Semaphore::new(parallel))};
    let app=Router::new().route("/health",get(health)).route("/v1/models",get(models))
        .route("/v1/chat/completions",post(chat)).with_state(state);
    let address=SocketAddr::new(IpAddr::V4(std::net::Ipv4Addr::LOCALHOST),port);
    let listener=tokio::net::TcpListener::bind(address).await?;
    println!("Rust local inference gateway on {address}");
    axum::serve(listener,app).await?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn rejects_remote_servers(){
        for s in ["https://api.example.com/v1","http://example.com/v1","http://127.0.0.1.evil.com/v1","http://user:pass@localhost:9931/v1"] {
            assert!(parse_upstream(s).is_err());
        }
        assert!(parse_upstream("http://127.0.0.1:9931/v1").is_ok());
    }
    #[test] fn caps_generation(){
        let input=json!({"model":"local","messages":[{"role":"user","content":"hello"}],"max_tokens":999999,"stream":true});
        let output=sanitize(input,512).unwrap();
        assert_eq!(output["max_tokens"],512);
        assert_eq!(output["stream"],false);
    }
}
