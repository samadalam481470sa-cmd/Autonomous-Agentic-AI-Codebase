# Desktop local AI onboarding (experimental)

The desktop app now opens a setup screen with basic hardware information, model and llama-server file pickers, GPU-layer selection, and a button to launch local inference. The packaged Rust gateway is started automatically after the llama.cpp server responds. The bundled Python API starts when the app launches.

Users must independently install a compatible llama.cpp binary. The setup UI supports downloading a GGUF model from a trusted Hugging Face HTTPS URL only when the user supplies a SHA256 checksum, the exact **reviewed model id**, the exact **license id**, and explicit license confirmation. The Electron main process checks [`security/model-policy.json`](../security/model-policy.json) before any network connection and again during the download IPC call. It verifies the checksum before storing the model in app data. This is a reviewed registry, not a model catalog: it does not verify the publisher or the file's safety, benchmark the GPU, or support resume. The reviewed models and permitted uses are listed in [LICENSING.md](LICENSING.md). Users may also select an existing GGUF file. The setup UI is not a driver installer.

To use the app immediately without a model, choose **Open Code Studio without AI**. The editor, file explorer and approved saves remain available; AI chat requires successful local inference.

### Packaging

The desktop workflow builds the Python backend and Rust runtime and stages both for Electron packaging on Windows, macOS and Linux. Packaging success is not proof of clean-machine startup. Test actual installers on all three OSes and verify model tool calling, editing, and process cleanup.

### Known risks and limitations

The desktop binds services to fixed localhost ports, has no code signing or notarization, and has no model download/update lifecycle. A local attacker or malicious website may attempt to reach local services. The application is not ready for untrusted multi-user deployment. GPU detection is informational; GPU acceleration must be confirmed with real model inference. The SQLite project store is single-user, not a distributed service.
