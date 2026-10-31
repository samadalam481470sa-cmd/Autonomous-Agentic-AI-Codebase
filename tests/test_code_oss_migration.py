"""Code-OSS migration product overlay tests do not clone huge upstream."""
import json
from pathlib import Path
import pytest
from scripts import code_oss_migrate as migration

def original():
    return {
        "nameShort":"Code - OSS","nameLong":"Code - OSS",
        "applicationName":"code-oss","licenseName":"MIT",
        "win32x64AppId":"{old}","defaultChatAgent":{"extensionId":"old"},
        "voiceWsUrl":"wss://vendor.example","retainMe":"untouched","linuxIconName":"code-oss",
    }

def test_branded_product_removes_service_defaults_but_preserves_license():
    product=migration.branded_product(original())
    migration.check_product(product)
    assert product["applicationName"]=="agentic-workbench"
    assert product["licenseName"]=="MIT"
    assert product["retainMe"]=="untouched"
    assert product["win32x64AppId"].startswith("{{")
    assert product["win32x64AppId"].endswith("}")
    assert product["win32x64AppId"]!="{old}"
    assert product["darwinProfileUUID"].count("-")==4
    assert product["linuxIconName"]=="code-oss"
    assert product["extensionsGallery"]["serviceUrl"]=="https://open-vsx.org/vscode/gallery"
    assert "defaultChatAgent" not in product
    assert "voiceWsUrl" not in product
    assert product==migration.branded_product(product)

def test_refuses_wrong_gallery_or_product_identity():
    product=migration.branded_product(original())
    product["extensionsGallery"]["serviceUrl"]="https://marketplace.visualstudio.com"
    with pytest.raises(RuntimeError):
        migration.check_product(product)

def test_overlay_writes_only_first_party_extension_and_validates(tmp_path):
    source=tmp_path/"vscode"
    (source/"extensions").mkdir(parents=True)
    (source/"product.json").write_text(json.dumps(migration.branded_product(original())))
    migration.copy_overlay(source)
    migration.validate_overlay(source)
    manifest=json.loads((source/"extensions"/"agentic-local"/"package.json").read_text())
    assert manifest["publisher"]=="agentic-workbench"
    assert manifest["main"]=="./extension.js"
    assert manifest["extensionKind"]==["ui"]
    assert (source/"extensions"/"agentic-local"/"extension.js").is_file()
    # Source files are linked in this repository, never mistaken for upstream.
    assert (migration.EXTENSION/"extension.js").read_bytes()==(source/"extensions"/"agentic-local"/"extension.js").read_bytes()

def test_overlay_catches_stale_files(tmp_path):
    source=tmp_path/"vscode"
    (source/"extensions").mkdir(parents=True)
    (source/"product.json").write_text(json.dumps(migration.branded_product(original())))
    migration.copy_overlay(source)
    (source/"extensions"/"agentic-local"/"sse.js").write_text("changed")
    with pytest.raises(RuntimeError,match="stale"):
        migration.validate_overlay(source)

def test_release_is_pinned():
    assert migration.PINNED_TAG=="1.144.0"
    assert migration.PINNED_COMMIT=="2c33b50b16c472efe58357d1d2a8a5414bc23fbf"
