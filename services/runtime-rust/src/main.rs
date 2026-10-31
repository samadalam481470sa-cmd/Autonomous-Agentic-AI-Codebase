//! Rust workspace scanner. No shell execution, model loading, or network access.
use serde::Serialize;
mod gateway;
use std::{env,fs,path::{Path,PathBuf},process};

#[derive(Serialize)]
struct Entry { path:String, bytes:u64, extension:String }
#[derive(Serialize)]
struct Report { files:Vec<Entry>, total_bytes:u64, truncated:bool }

fn walk(root:&Path,dir:&Path,entries:&mut Vec<Entry>,bytes:&mut u64,limit:usize) -> std::io::Result<bool> {
    if entries.len()>=limit { return Ok(true); }
    for item in fs::read_dir(dir)? {
        let item=item?;
        let path=item.path();
        let meta=fs::symlink_metadata(&path)?;
        if meta.file_type().is_symlink() {continue;}
        if meta.is_dir() {
            if [".git","node_modules",".venv","target","dist","build"].contains(&item.file_name().to_string_lossy().as_ref()){continue;}
            if walk(root,&path,entries,bytes,limit)? {return Ok(true);}
        } else if meta.is_file() {
            let relative=path.strip_prefix(root).unwrap_or(&path).to_string_lossy().to_string();
            *bytes=bytes.saturating_add(meta.len());
            entries.push(Entry{path:relative,bytes:meta.len(),extension:path.extension().unwrap_or_default().to_string_lossy().to_string()});
            if entries.len()>=limit {return Ok(true);}
        }
    }
    Ok(false)
}
fn scan(root:&Path,limit:usize)->Result<Report,String>{
    let root=fs::canonicalize(root).map_err(|e|e.to_string())?;
    if !root.is_dir(){return Err("Workspace must be a directory".into());}
    let mut files=Vec::new();let mut total_bytes=0;
    let truncated=walk(&root,&root,&mut files,&mut total_bytes,limit).map_err(|e|e.to_string())?;
    files.sort_by(|a,b|a.path.cmp(&b.path));
    Ok(Report{files,total_bytes,truncated})
}
#[tokio::main]
async fn main(){
    let args:Vec<String>=env::args().collect();
    if args.len()==2 && args[1]=="serve" {
        if let Err(e)=gateway::serve().await {eprintln!("Gateway error: {e}");process::exit(1)}
        return;
    }
    if args.len()!=3 || args[1]!="scan" {
        eprintln!("Usage: agentic-runtime scan <workspace-directory> | serve");
        process::exit(2);
    }
    match scan(&PathBuf::from(&args[2]),10000){
        Ok(report)=>println!("{}",serde_json::to_string(&report).unwrap()),
        Err(error)=>{eprintln!("{error}");process::exit(1);}
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn missing_directory_fails(){assert!(scan(Path::new("/a-path-that-does-not-exist-agentic"),100).is_err());}
    #[test] fn empty_limit_truncates(){let root=env::temp_dir();assert!(scan(&root,0).unwrap().truncated);}
}
