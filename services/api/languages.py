"""Language support registry and syntax-aware file classification.

Editing any UTF-8 language is possible; execution requires separate, approved
toolchains. This registry describes common languages, not every language.
"""
from pathlib import PurePath
from fastapi import APIRouter
router=APIRouter(prefix="/api/languages",tags=["languages"])
LANGUAGES={
"python":(".py",".pyi"),"typescript":(".ts",".tsx"),"javascript":(".js",".jsx",".mjs",".cjs"),
"rust":(".rs",),"go":(".go",),"java":(".java",),"kotlin":(".kt",".kts"),"scala":(".scala",),
"c":(".c",".h"),"cpp":(".cpp",".cc",".cxx",".hpp",".hh"),"csharp":(".cs",),
"swift":(".swift",),"objective-c":(".m",".mm"),"dart":(".dart",),"php":(".php",),
"ruby":(".rb",),"elixir":(".ex",".exs"),"erlang":(".erl",),"haskell":(".hs",),
"lua":(".lua",),"perl":(".pl",".pm"),"r":(".r",),"julia":(".jl",),
"shell":(".sh",".bash",".zsh"),"powershell":(".ps1",".psm1"),"sql":(".sql",),
"html":(".html",".htm"),"css":(".css",),"scss":(".scss",),"vue":(".vue",),
"svelte":(".svelte",),"json":(".json",),"yaml":(".yaml",".yml"),"toml":(".toml",),
"xml":(".xml",),"graphql":(".graphql",".gql"),"protobuf":(".proto",),
"terraform":(".tf",".tfvars"),"dockerfile":(".dockerfile",),
"markdown":(".md",),"assembly":(".asm",".s"),"zig":(".zig",),"nim":(".nim",),
"ocaml":(".ml",".mli"),"fsharp":(".fs",".fsx"),"clojure":(".clj",".cljs"),
"groovy":(".groovy",),"solidity":(".sol",),"move":(".move",),"cobol":(".cbl",".cob"),
"fortran":(".f90",".f95",".f"),"pascal":(".pas",),"ada":(".adb",".ads"),
"matlab":(".m",),"tex":(".tex",),"verilog":(".v",".sv")
}
EXTENSIONS={extension:language for language,extensions in LANGUAGES.items() for extension in extensions}
def identify(filename):
    name=PurePath(filename).name.lower()
    if name=="dockerfile":return "dockerfile"
    return EXTENSIONS.get(PurePath(name).suffix,"plaintext")
@router.get("")
def list_languages():
    return {"languages":[{"name":name,"extensions":list(extensions)} for name,extensions in sorted(LANGUAGES.items())],"unknown_files":"editable as UTF-8 plain text","execution":"separate approved sandbox only"}
