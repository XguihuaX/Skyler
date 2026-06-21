// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_yaml::Value;
use std::env;
use std::fs;
use std::path::PathBuf;

#[tauri::command]
fn ping() -> &'static str {
    "pong"
}

fn locate_config_yaml() -> Result<PathBuf, String> {
    let mut dir = env::current_dir().map_err(|e| format!("current_dir: {}", e))?;
    for _ in 0..6 {
        let candidate = dir.join("config.yaml");
        if candidate.is_file() {
            return Ok(candidate);
        }
        if !dir.pop() {
            break;
        }
    }
    let manifest_fallback = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config.yaml");
    if manifest_fallback.is_file() {
        return Ok(manifest_fallback);
    }
    Err("config.yaml not found within 5 parent directories of CWD".to_string())
}

#[tauri::command]
fn write_config_field(key_path: String, value: Value) -> Result<(), String> {
    if key_path.is_empty() {
        return Err("key_path is empty".to_string());
    }
    let config_path = locate_config_yaml()?;

    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("read config: {}", e))?;
    let mut yaml: Value = serde_yaml::from_str(&content)
        .map_err(|e| format!("parse yaml: {}", e))?;

    let keys: Vec<&str> = key_path.split('.').collect();
    let mut current = &mut yaml;
    for k in &keys[..keys.len() - 1] {
        let mapping = current
            .as_mapping_mut()
            .ok_or_else(|| format!("path segment '{}' is not under a mapping", k))?;
        let key = Value::String((*k).to_string());
        // 2026-06-21 fix: 中间段不存在时自动建空 mapping(原 gate 抛错让
        // 新 config 段如 thinking: 永远写不进 → toggleConfigField 回滚 → UI
        // 看着没反馈)。从此任意新嵌套段都能 first-time toggle 自动落 yaml,
        // 无须手动 pre-seed。is_mapping 校验保留 - 防 path 段命中已存在的
        // 非 mapping 值(scalar / list)被误覆盖。
        if !mapping.contains_key(&key) {
            mapping.insert(key.clone(), Value::Mapping(Default::default()));
        }
        current = mapping.get_mut(&key).unwrap();
        if !current.is_mapping() {
            return Err(format!("intermediate key '{}' is not a mapping", k));
        }
    }
    let last = *keys.last().unwrap();
    let mapping = current
        .as_mapping_mut()
        .ok_or_else(|| "leaf parent is not a mapping".to_string())?;
    mapping.insert(Value::String(last.to_string()), value);

    let new_content = serde_yaml::to_string(&yaml)
        .map_err(|e| format!("serialize yaml: {}", e))?;
    fs::write(&config_path, new_content)
        .map_err(|e| format!("write config: {}", e))?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![ping, write_config_field])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
