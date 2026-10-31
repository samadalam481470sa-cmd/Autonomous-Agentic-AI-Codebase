# Desktop local AI onboarding (experimental)

The desktop app now opens a setup screen with basic hardware information, model and llama-server file pickers, GPU-layer selection, and a button to launch local inference. The packaged Rust gateway is started automatically after the llama.cpp server responds. The bundled Python API starts when the app launches.

Users must **independently download and install** a compatible llama.cpp binary and a licensed GGUF model. The app does not yet provide a verified in-app download catalog, checksum verification, model license acceptance or GPU benchmark. The setup UI is not a driver installer.

To use the app immediately without a model, choose **Open Code Studio without AI**. The editor, file explorer and approved saves remain available; AI chat requires successful local inference.

### Packaging

The desktop workflow builds the Python backend and Rust runtime and stages both for Electron packaging on Windows, macOS and Linux. Packaging success is not proof of clean-machine startup. Test actual installers on all three OSes and verify model tool calling, editing, and process cleanup.

### Known risks and limitations

The desktop binds services to fixed localhost ports, has no code signing or notarization, and has no model download/update lifecycle. A local attacker or malicious website may attempt to reach local services. The application is not ready for untrusted multi-user deployment. GPU detection is informational; GPU acceleration must be confirmed with real model inference. The SQLite project store is single-user, not a distributed service.
