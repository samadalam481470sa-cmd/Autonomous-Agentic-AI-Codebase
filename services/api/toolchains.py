"""Polyglot toolchain registry, discovery, command planning and execution.

Every language is described declaratively: executables to probe, optional
single-file check/compile/execute templates, optional project-level build and
test commands, a starter file and an install hint. Templates are argv lists
expanded here and executed **without a shell**, so a file path or language name
can never inject extra commands.

Languages outside the built-in registry can be added at runtime with
``register_custom``; the definition is validated and persisted to a local JSON
file, so "any language" means any toolchain the owner installs, not only the
languages shipped here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .path_safety import unsafe_relative_path

from .languages import LANGUAGES

MAX_ARGV = 64
MAX_ARG_CHARS = 2048
MAX_OUTPUT = 20000
MAX_STDERR = 8000
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900
IGNORED_DIRS = {
    ".git", ".agent", ".polyglot", "node_modules", ".venv", "venv", "env",
    "target", "dist", "build", "__pycache__", ".next", ".cache", "vendor",
    ".mypy_cache", ".pytest_cache", "coverage",
}
PLACEHOLDERS = {"{exe}", "{file}", "{out}", "{stem}"}
LANGUAGE_NAME = re.compile(r"^[a-z][a-z0-9+#._-]{0,31}$")
EXTENSION = re.compile(r"^\.[A-Za-z0-9_+-]{1,12}$")


def _t(category, probes, *, check=None, compile=None, execute=None, run=None,
       test=None, build=None, install="", require=()):
    return {
        "category": category, "probes": probes, "check": check,
        "compile": compile, "execute": execute, "run": run, "test": test,
        "build": build, "install": install, "require": list(require),
    }


# Templates may use {exe} (resolved executable), {file} (target path),
# {out} (temporary output directory) and {stem} (target file stem).
SPECS = {
    "python": _t("interpreted", [["python3", "--version"], ["python", "--version"]],
                 check=["{exe}", "-m", "py_compile", "{file}"],
                 run=["{exe}", "-B", "{file}"],
                 test=["{exe}", "-m", "pytest", "-q"],
                 install="Install Python 3.11+ from https://www.python.org/downloads/"),
    "javascript": _t("interpreted", [["node", "--version"]],
                     check=["{exe}", "--check", "{file}"],
                     run=["{exe}", "{file}"],
                     test=["npm", "test", "--silent"],
                     build=["npm", "run", "build", "--silent"],
                     install="Install Node.js 20+ from https://nodejs.org/"),
    "typescript": _t("interpreted", [["tsc", "--version"]],
                     check=["{exe}", "--noEmit", "--skipLibCheck", "{file}"],
                     compile=["{exe}", "{file}", "--outDir", "{out}", "--module", "commonjs",
                              "--target", "es2020", "--skipLibCheck"],
                     execute=["node", "{out}/{stem}.js"],
                     test=["npm", "test", "--silent"],
                     build=["npm", "run", "build", "--silent"],
                     install="npm install -g typescript, then install Node.js",
                     require=["node"]),
    "rust": _t("compiled", [["rustc", "--version"]],
               compile=["{exe}", "--edition", "2021", "-o", "{out}/program", "{file}"],
               execute=["{out}/program"],
               test=["cargo", "test", "--quiet"],
               build=["cargo", "build", "--quiet"],
               install="Install Rust from https://rustup.rs/"),
    "go": _t("compiled", [["go", "version"]],
             compile=["{exe}", "build", "-o", "{out}/program", "{file}"],
             execute=["{out}/program"],
             test=["{exe}", "test", "./..."],
             build=["{exe}", "build", "./..."],
             install="Install Go from https://go.dev/dl/"),
    "java": _t("compiled", [["javac", "-version"]],
               compile=["{exe}", "-d", "{out}", "{file}"],
               execute=["java", "-cp", "{out}", "{stem}"],
               test=["gradle", "test", "--quiet"],
               build=["gradle", "build", "--quiet"],
               install="Install a JDK 17+ from https://adoptium.net/",
               require=["java"]),
    "kotlin": _t("compiled", [["kotlinc", "-version"]],
                 compile=["{exe}", "{file}", "-include-runtime", "-d", "{out}/app.jar"],
                 execute=["java", "-jar", "{out}/app.jar"],
                 test=["gradle", "test", "--quiet"],
                 build=["gradle", "build", "--quiet"],
                 install="Install Kotlin from https://kotlinlang.org/docs/command-line.html",
                 require=["java"]),
    "scala": _t("interpreted", [["scala", "-version"]],
                run=["{exe}", "{file}"],
                install="Install Scala from https://www.scala-lang.org/download/"),
    "c": _t("compiled", [["gcc", "--version"], ["clang", "--version"], ["cc", "--version"]],
            compile=["{exe}", "-O0", "-o", "{out}/program", "{file}"],
            execute=["{out}/program"],
            install="Install GCC or Clang and a C standard library"),
    "cpp": _t("compiled", [["g++", "--version"], ["clang++", "--version"], ["c++", "--version"]],
              compile=["{exe}", "-std=c++17", "-O0", "-o", "{out}/program", "{file}"],
              execute=["{out}/program"],
              install="Install GCC or Clang with C++ support"),
    "csharp": _t("compiled", [["dotnet", "--version"]],
                 build=["{exe}", "build", "--nologo", "-v", "q"],
                 test=["{exe}", "test", "--nologo", "-v", "q"],
                 install="Install the .NET SDK from https://dotnet.microsoft.com/download"),
    "swift": _t("compiled", [["swiftc", "--version"]],
                compile=["{exe}", "-o", "{out}/program", "{file}"],
                execute=["{out}/program"],
                test=["swift", "test"],
                install="Install Swift from https://www.swift.org/install/"),
    "objective-c": _t("compiled", [["clang", "--version"]],
                      compile=["{exe}", "-framework", "Foundation", "-o", "{out}/program", "{file}"],
                      execute=["{out}/program"],
                      install="Install clang and the platform Foundation framework (macOS)")
    ,
    "dart": _t("interpreted", [["dart", "--version"]],
               check=["{exe}", "analyze", "{file}"],
               run=["{exe}", "run", "{file}"],
               test=["{exe}", "test"],
               install="Install Dart from https://dart.dev/get-dart"),
    "ruby": _t("interpreted", [["ruby", "--version"]],
               check=["{exe}", "-c", "{file}"],
               run=["{exe}", "{file}"],
               install="Install Ruby from https://www.ruby-lang.org/en/downloads/"),
    "php": _t("interpreted", [["php", "--version"]],
              check=["{exe}", "-l", "{file}"],
              run=["{exe}", "{file}"],
              install="Install PHP from https://www.php.net/downloads"),
    "perl": _t("interpreted", [["perl", "-v"]],
               check=["{exe}", "-c", "{file}"],
               run=["{exe}", "{file}"],
               install="Install Perl from https://www.perl.org/get.html"),
    "lua": _t("interpreted", [["lua", "-v"], ["lua5.4", "-v"], ["luajit", "-v"]],
              run=["{exe}", "{file}"],
              install="Install Lua from https://www.lua.org/download.html"),
    "r": _t("interpreted", [["Rscript", "--version"]],
            run=["{exe}", "--vanilla", "-f", "{file}"],
            install="Install R from https://cran.r-project.org/"),
    "julia": _t("interpreted", [["julia", "--version"]],
                run=["{exe}", "{file}"],
                install="Install Julia from https://julialang.org/downloads/"),
    "haskell": _t("interpreted", [["runghc", "--version"]],
                  run=["{exe}", "{file}"],
                  build=["cabal", "build"],
                  test=["cabal", "test"],
                  install="Install GHCup from https://www.haskell.org/ghcup/"),
    "elixir": _t("interpreted", [["elixir", "--version"]],
                 run=["{exe}", "{file}"],
                 test=["mix", "test"],
                 install="Install Elixir from https://elixir-lang.org/install.html"),
    "erlang": _t("interpreted", [["escript", "--version"]],
                 run=["{exe}", "{file}"],
                 install="Install Erlang/OTP from https://www.erlang.org/downloads"),
    "ocaml": _t("interpreted", [["ocaml", "-version"]],
                run=["{exe}", "{file}"],
                build=["dune", "build"],
                install="Install OCaml from https://ocaml.org/install"),
    "fsharp": _t("interpreted", [["dotnet", "--version"]],
                 run=["{exe}", "fsi", "{file}"],
                 build=["{exe}", "build", "--nologo"],
                 test=["{exe}", "test", "--nologo"],
                 install="Install the .NET SDK from https://dotnet.microsoft.com/download"),
    "clojure": _t("interpreted", [["clojure", "-version"], ["clj", "-version"]],
                  run=["{exe}", "{file}"],
                  install="Install Clojure from https://clojure.org/guides/install_clojure"),
    "groovy": _t("interpreted", [["groovy", "--version"]],
                 run=["{exe}", "{file}"],
                 install="Install Groovy from https://groovy-lang.org/install.html"),
    "shell": _t("interpreted", [["bash", "--version"]],
                check=["{exe}", "-n", "{file}"],
                run=["{exe}", "{file}"],
                install="Install bash (available by default on most Unix systems)"),
    "powershell": _t("interpreted", [["pwsh", "-Version"], ["powershell", "-Version"]],
                     run=["{exe}", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "{file}"],
                     install="Install PowerShell 7 from https://microsoft.com/powershell"),
    "sql": _t("query", [["sqlite3", "--version"]],
              check=["{exe}", "-bail", "{file}"],
              run=["{exe}", "-bail", "{file}"],
              install="Install the SQLite CLI from https://sqlite.org/download.html"),
    "json": _t("data", [["python3", "--version"]],
               check=["{exe}", "-m", "json.tool", "{file}"],
               install="Validated with the Python standard library"),
    "toml": _t("data", [["python3", "--version"]],
               check=["{exe}", "-c", "import sys,tomllib;tomllib.load(open(sys.argv[1],'rb'))", "{file}"],
               install="Validated with Python 3.11+ tomllib"),
    "xml": _t("data", [["python3", "--version"]],
              check=["{exe}", "-c", "import sys,xml.etree.ElementTree as E;E.parse(sys.argv[1])", "{file}"],
              install="Validated with the Python standard library"),
    "scss": _t("markup", [["sass", "--version"]],
               check=["{exe}", "{file}", "{out}/out.css"],
               install="npm install -g sass"),
    "protobuf": _t("schema", [["protoc", "--version"]],
                   check=["{exe}", "--descriptor_set_out={out}/schema.pb", "{file}"],
                   install="Install protoc from https://github.com/protocolbuffers/protobuf/releases"),
    "terraform": _t("schema", [["terraform", "version"]],
                    check=["{exe}", "validate"],
                    build=["{exe}", "validate"],
                    install="Install Terraform from https://developer.hashicorp.com/terraform/install"),
    "solidity": _t("compiled", [["solc", "--version"]],
                   check=["{exe}", "--bin", "{file}"],
                   install="Install solc from https://docs.soliditylang.org/en/latest/installing-solidity.html"),
    "assembly": _t("compiled", [["nasm", "-v"]],
                   compile=["{exe}", "-f", "elf64", "-o", "{out}/program.o", "{file}"],
                   install="Install NASM from https://www.nasm.us/"),
    "zig": _t("compiled", [["zig", "version"]],
              compile=["{exe}", "build-exe", "{file}", "-femit-bin={out}/program"],
              execute=["{out}/program"],
              test=["{exe}", "build", "test"],
              build=["{exe}", "build"],
              install="Install Zig from https://ziglang.org/download/"),
    "nim": _t("compiled", [["nim", "--version"]],
              compile=["{exe}", "c", "-o:{out}/program", "{file}"],
              execute=["{out}/program"],
              install="Install Nim from https://nim-lang.org/install.html"),
    "cobol": _t("compiled", [["cobc", "--version"]],
                compile=["{exe}", "-x", "-o", "{out}/program", "{file}"],
                execute=["{out}/program"],
                install="Install GnuCOBOL from https://gnucobol.sourceforge.io/"),
    "fortran": _t("compiled", [["gfortran", "--version"]],
                  compile=["{exe}", "-o", "{out}/program", "{file}"],
                  execute=["{out}/program"],
                  install="Install gfortran from https://gcc.gnu.org/fortran/"),
    "pascal": _t("compiled", [["fpc", "-iV"]],
                 compile=["{exe}", "-o{out}/program", "{file}"],
                 execute=["{out}/program"],
                 install="Install Free Pascal from https://www.freepascal.org/"),
    "ada": _t("compiled", [["gnatmake", "--version"]],
              compile=["{exe}", "-o", "{out}/program", "{file}"],
              execute=["{out}/program"],
              install="Install GNAT from https://www.gnu.org/software/gnat/"),
    "matlab": _t("interpreted", [["octave", "--version"]],
                 run=["{exe}", "--quiet", "{file}"],
                 install="Install GNU Octave from https://octave.org/download (MATLAB syntax)"),
    "tex": _t("markup", [["pdflatex", "--version"]],
              build=["{exe}", "-interaction=nonstopmode", "-halt-on-error", "{file}"],
              install="Install TeX Live or MiKTeX"),
    "verilog": _t("hardware", [["iverilog", "-V"]],
                  check=["{exe}", "-o", "{out}/design.out", "{file}"],
                  install="Install Icarus Verilog from http://iverilog.icarus.com/"),
    "crystal": _t("compiled", [["crystal", "--version"]],
                  check=["{exe}", "build", "--no-codegen", "{file}"],
                  run=["{exe}", "run", "{file}"],
                  install="Install Crystal from https://crystal-lang.org/install/"),
    "elm": _t("compiled", [["elm", "--version"]],
              build=["{exe}", "make", "{file}", "--output=/dev/null"],
              install="Install Elm from https://guide.elm-lang.org/install/elm.html"),
    "racket": _t("interpreted", [["racket", "--version"]],
                 run=["{exe}", "{file}"],
                 install="Install Racket from https://racket-lang.org/download/"),
    "prolog": _t("interpreted", [["swipl", "--version"]],
                 run=["{exe}", "-q", "-t", "halt", "-s", "{file}"],
                 install="Install SWI-Prolog from https://www.swi-prolog.org/download/stable"),
    "d": _t("compiled", [["dmd", "--version"]],
            compile=["{exe}", "-of{out}/program", "{file}"],
            execute=["{out}/program"],
            install="Install DMD from https://dlang.org/download.html"),
    "gleam": _t("compiled", [["gleam", "--version"]],
                build=["{exe}", "build"],
                test=["{exe}", "test"],
                install="Install Gleam from https://gleam.run/getting-started/installing/"),
    "nix": _t("data", [["nix-instantiate", "--version"]],
              check=["{exe}", "--parse", "{file}"],
              install="Install Nix from https://nixos.org/download/"),
    "glsl": _t("hardware", [["glslangValidator", "--version"]],
               check=["{exe}", "{file}"],
               install="Install glslangValidator from https://github.com/KhronosGroup/glslang/releases"),
    "html": _t("markup", [], install="Static markup; no compiler required"),
    "css": _t("markup", [], install="Static stylesheet; no compiler required"),
    "vue": _t("markup", [["npm", "--version"]],
              test=["npm", "test", "--silent"],
              build=["npm", "run", "build", "--silent"],
              install="Install Node.js and the project's npm dependencies"),
    "svelte": _t("markup", [["npm", "--version"]],
                 test=["npm", "test", "--silent"],
                 build=["npm", "run", "build", "--silent"],
                 install="Install Node.js and the project's npm dependencies"),
    "yaml": _t("data", [], install="YAML data; no compiler required"),
    "graphql": _t("schema", [], install="GraphQL schema; no compiler required"),
    "dockerfile": _t("schema", [], install="Requires Docker; not executed by this registry"),
    "markdown": _t("markup", [], install="Documentation; no compiler required"),
    "move": _t("schema", [], install="Requires the Move toolchain; not executed by this registry"),
}

# Starter file name and runnable hello-world source for each scaffoldable language.
DEFAULT_FILES = {
    "python": "main.py", "javascript": "main.js", "typescript": "main.ts",
    "rust": "main.rs", "go": "main.go", "java": "Main.java", "kotlin": "Main.kt",
    "scala": "Main.scala", "c": "main.c", "cpp": "main.cpp", "csharp": "Program.cs",
    "swift": "main.swift", "objective-c": "main.m", "dart": "main.dart",
    "ruby": "main.rb", "php": "main.php", "perl": "main.pl", "lua": "main.lua",
    "r": "main.r", "julia": "main.jl", "haskell": "main.hs", "elixir": "main.exs",
    "erlang": "main.escript", "ocaml": "main.ml", "fsharp": "main.fsx",
    "clojure": "main.clj", "groovy": "main.groovy", "shell": "main.sh",
    "powershell": "main.ps1", "sql": "main.sql", "json": "data.json",
    "toml": "config.toml", "xml": "data.xml", "scss": "style.scss",
    "protobuf": "message.proto", "terraform": "main.tf", "solidity": "main.sol",
    "assembly": "main.asm", "zig": "main.zig", "nim": "main.nim",
    "cobol": "main.cob", "fortran": "main.f90", "pascal": "main.pas",
    "ada": "main.adb", "matlab": "main.m", "tex": "main.tex", "verilog": "main.v",
    "crystal": "main.cr", "elm": "Main.elm", "racket": "main.rkt", "prolog": "main.pro",
    "d": "main.d", "gleam": "main.gleam", "nix": "default.nix", "glsl": "shader.glsl",
    "html": "index.html", "css": "style.css", "vue": "App.vue", "svelte": "App.svelte",
    "yaml": "config.yaml", "graphql": "schema.graphql", "dockerfile": "Dockerfile",
    "markdown": "README.md",
}

HELLO = {
    "python": 'print("hello from python")\n',
    "javascript": 'console.log("hello from javascript");\n',
    "typescript": 'const message: string = "hello from typescript";\nconsole.log(message);\n',
    "rust": 'fn main() { println!("hello from rust"); }\n',
    "go": 'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hello from go") }\n',
    "java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("hello from java");\n    }\n}\n',
    "kotlin": 'fun main() { println("hello from kotlin") }\n',
    "scala": '@main def hello(): Unit = println("hello from scala")\n',
    "c": '#include <stdio.h>\n\nint main(void) {\n    puts("hello from c");\n    return 0;\n}\n',
    "cpp": '#include <iostream>\n\nint main() {\n    std::cout << "hello from cpp" << std::endl;\n    return 0;\n}\n',
    "csharp": 'class Program {\n    static void Main() { System.Console.WriteLine("hello from csharp"); }\n}\n',
    "swift": 'print("hello from swift")\n',
    "objective-c": '#import <Foundation/Foundation.h>\n\nint main(void) {\n    @autoreleasepool {\n        NSLog(@"hello from objective-c");\n    }\n    return 0;\n}\n',
    "dart": 'void main() {\n  print("hello from dart");\n}\n',
    "ruby": 'puts "hello from ruby"\n',
    "php": '<?php\necho "hello from php\\n";\n',
    "perl": 'use strict;\nuse warnings;\nprint "hello from perl\\n";\n',
    "lua": 'print("hello from lua")\n',
    "r": 'cat("hello from r\\n")\n',
    "julia": 'println("hello from julia")\n',
    "haskell": 'main :: IO ()\nmain = putStrLn "hello from haskell"\n',
    "elixir": 'IO.puts("hello from elixir")\n',
    "erlang": 'main(_) ->\n    io:format("hello from erlang~n").\n',
    "ocaml": 'print_endline "hello from ocaml";;\n',
    "fsharp": 'printfn "hello from fsharp"\n',
    "clojure": '(println "hello from clojure")\n',
    "groovy": 'println "hello from groovy"\n',
    "shell": '#!/usr/bin/env bash\nset -euo pipefail\necho "hello from shell"\n',
    "powershell": 'Write-Output "hello from powershell"\n',
    "sql": "SELECT 'hello from sql';\n",
    "json": '{"hello": "from json"}\n',
    "toml": 'hello = "from toml"\n',
    "xml": '<?xml version="1.0" encoding="UTF-8"?>\n<greeting>hello from xml</greeting>\n',
    "scss": '$color: #4f6ef7;\nbody { color: $color; }\n',
    "protobuf": 'syntax = "proto3";\n\nmessage Greeting {\n  string message = 1;\n}\n',
    "terraform": 'terraform {\n  required_version = ">= 1.5.0"\n}\n',
    "solidity": '// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n\ncontract Hello {\n    function greet() public pure returns (string memory) {\n        return "hello from solidity";\n    }\n}\n',
    "assembly": 'global _start\n\nsection .text\n_start:\n    mov rax, 1\n    mov rdi, 1\n    lea rsi, [rel message]\n    mov rdx, 18\n    syscall\n    mov rax, 60\n    xor rdi, rdi\n    syscall\n\nsection .data\nmessage: db "hello from assembly", 10\n',
    "zig": 'const std = @import("std");\n\npub fn main() !void {\n    std.debug.print("hello from zig\\n", .{});\n}\n',
    "nim": 'echo "hello from nim"\n',
    "cobol": '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n       PROCEDURE DIVISION.\n           DISPLAY "hello from cobol".\n           STOP RUN.\n',
    "fortran": 'program hello\n    print *, "hello from fortran"\nend program hello\n',
    "pascal": 'program Hello;\nbegin\n  writeln(\'hello from pascal\');\nend.\n',
    "ada": 'with Ada.Text_IO; use Ada.Text_IO;\nprocedure Main is\nbegin\n   Put_Line ("hello from ada");\nend Main;\n',
    "matlab": 'disp("hello from matlab");\n',
    "tex": '\\documentclass{article}\n\\begin{document}\nhello from tex\n\\end{document}\n',
    "verilog": 'module hello;\n  initial begin\n    $display("hello from verilog");\n    $finish;\n  end\nendmodule\n',
    "crystal": 'puts "hello from crystal"\n',
    "elm": 'module Main exposing (main)\n\nimport Html exposing (text)\n\nmain =\n    text "hello from elm"\n',
    "racket": '#lang racket\n(displayln "hello from racket")\n',
    "prolog": ":- initialization(main).\nmain :- writeln('hello from prolog'), halt.\n",
    "d": 'import std.stdio;\n\nvoid main() {\n    writeln("hello from d");\n}\n',
    "gleam": 'import gleam/io\n\npub fn main() {\n  io.println("hello from gleam")\n}\n',
    "nix": '{ hello = "from nix"; }\n',
    "glsl": '#version 450\nvoid main() { gl_FragColor = vec4(1.0); }\n',
    "html": '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>hello</title></head>\n<body><h1>hello from html</h1></body></html>\n',
    "css": ':root { color-scheme: light dark; }\nbody { font-family: system-ui, sans-serif; }\n',
    "vue": '<script setup>\nconst message = "hello from vue";\n</script>\n\n<template>\n  <h1>{{ message }}</h1>\n</template>\n',
    "svelte": '<script>\n  let message = "hello from svelte";\n</script>\n\n<h1>{message}</h1>\n',
    "yaml": 'hello: from yaml\n',
    "graphql": 'type Query {\n  hello: String!\n}\n',
    "dockerfile": 'FROM alpine:3.20\nCMD ["echo", "hello from docker"]\n',
    "markdown": '# hello from markdown\n',
}

MANIFESTS = {
    "csharp": {
        "hello.csproj": '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n    <TargetFramework>net8.0</TargetFramework>\n    <ImplicitUsings>enable</ImplicitUsings>\n  </PropertyGroup>\n</Project>\n'
    },
}

ALIASES = {
    "py": "python", "python3": "python", "js": "javascript", "node": "javascript",
    "ts": "typescript", "rs": "rust", "golang": "go", "c++": "cpp", "cxx": "cpp",
    "c#": "csharp", "cs": "csharp", "objc": "objective-c", "objectivec": "objective-c",
    "rb": "ruby", "sh": "shell", "bash": "shell", "zsh": "shell", "ps1": "powershell",
    "postgresql": "sql", "mysql": "sql", "sqlite": "sql", "yml": "yaml", "md": "markdown",
    "sol": "solidity", "asm": "assembly", "kt": "kotlin", "kts": "kotlin", "fs": "fsharp",
    "ml": "ocaml", "hs": "haskell", "ex": "elixir", "exs": "elixir", "jl": "julia",
    "docker": "dockerfile", "tf": "terraform", "proto": "protobuf", "gql": "graphql",
}

_CACHE: dict[str, object] = {"at": 0.0, "value": None}


def custom_path() -> Path:
    return Path(os.getenv("POLYGLOT_TOOLCHAINS_PATH", str(Path.home() / ".agentic-ai" / "toolchains.json"))).expanduser()


def normalize(language: str) -> str:
    if not isinstance(language, str):
        raise ValueError("Language must be a string")
    name = language.strip().lower().replace(" ", "-")
    return ALIASES.get(name, name)


def custom_specs() -> dict:
    path = custom_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("languages", raw) if isinstance(raw, dict) else {}
    if not isinstance(entries, dict):
        return {}
    result = {}
    for name, entry in entries.items():
        try:
            result[normalize(name)] = _validate_custom(name, entry)
        except ValueError:
            continue
    return result


def _validate_argv(name, value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, list) or not value or len(value) > MAX_ARGV:
        raise ValueError(f"{name}: command must be a non-empty argv list")
    result = []
    for part in value:
        if not isinstance(part, str) or not part or len(part) > MAX_ARG_CHARS:
            raise ValueError(f"{name}: command arguments must be short strings")
        if "\x00" in part or "\n" in part:
            raise ValueError(f"{name}: command arguments cannot contain control characters")
        unknown = set(re.findall(r"\{[a-z]+\}", part)) - PLACEHOLDERS
        if unknown:
            raise ValueError(f"{name}: unsupported placeholder {sorted(unknown)[0]}")
        result.append(part)
    if not result[0].strip():
        raise ValueError(f"{name}: executable is required")
    return result


def _validate_custom(name, entry):
    if not isinstance(name, str) or not LANGUAGE_NAME.fullmatch(name.strip().lower()):
        raise ValueError("Custom language names must be 1-32 lowercase identifier characters")
    if not isinstance(entry, dict):
        raise ValueError("Custom language definition must be an object")
    extensions = entry.get("extensions", [])
    if not isinstance(extensions, list) or len(extensions) > 32:
        raise ValueError("extensions must be a list of at most 32 entries")
    clean_extensions = []
    for extension in extensions:
        if not isinstance(extension, str) or not EXTENSION.fullmatch(extension):
            raise ValueError(f"Invalid extension: {extension!r}")
        clean_extensions.append(extension.lower())
    probes = entry.get("probes", [])
    if not isinstance(probes, list) or len(probes) > 8:
        raise ValueError("probes must be a list of at most 8 commands")
    clean_probes = [_validate_argv("probes", probe, required=True) for probe in probes]
    templates = {}
    for action in ("check", "compile", "execute", "run", "test", "build"):
        templates[action] = _validate_argv(action, entry.get(action))
    if not clean_probes and not any(templates.values()):
        raise ValueError("A custom language needs probes or at least one command")
    uses_exe = any("{exe}" in part for template in templates.values() if template for part in template)
    if uses_exe and not clean_probes:
        raise ValueError("Templates using {exe} need at least one probe command")
    install = entry.get("install", "Installed by the owner")
    if not isinstance(install, str) or len(install) > 500:
        raise ValueError("install hint must be a short string")
    default_file = entry.get("default_file")
    if default_file is not None:
        if not isinstance(default_file, str) or len(default_file) > 200 or "/" in default_file or "\\" in default_file:
            raise ValueError("default_file must be a bare file name")
    hello = entry.get("hello")
    if hello is not None and (not isinstance(hello, str) or len(hello) > 100_000):
        raise ValueError("hello must be source text under 100 KB")
    return {
        "category": entry.get("category", "custom") if isinstance(entry.get("category", "custom"), str) else "custom",
        "extensions": clean_extensions,
        "probes": clean_probes, "require": [], "install": install,
        "default_file": default_file, "hello": hello,
        **templates,
    }


def register_custom(entry: dict, overwrite: bool = False) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("A language definition object is required")
    name = normalize(str(entry.get("language", "")))
    if name in SPECS and not overwrite:
        raise ValueError(f"{name} is built in; pass overwrite=true to replace it")
    validated = _validate_custom(name, entry)
    path = custom_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            existing = loaded.get("languages", loaded) if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            existing = {}
    stored = {
        "extensions": [extension.lower() for extension in entry.get("extensions", [])],
        **{key: value for key, value in entry.items()
           if key in ("category", "probes", "check", "compile", "execute", "run",
                      "test", "build", "install", "default_file", "hello")},
    }
    existing[name] = stored
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"languages": existing}, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)
    _CACHE["value"] = None
    return get_spec(name)


def get_spec(language: str) -> dict:
    name = normalize(language)
    custom = custom_specs()
    if name in custom:
        spec = dict(custom[name])
        spec.setdefault("default_file", None)
        spec.setdefault("hello", None)
        spec["custom"] = True
        spec["name"] = name
        return spec
    if name not in SPECS:
        raise KeyError(f"Unknown language: {language}. Register it with /api/polyglot/register.")
    spec = dict(SPECS[name])
    spec.update({
        "name": name, "custom": False,
        "default_file": DEFAULT_FILES.get(name),
        "hello": HELLO.get(name),
    })
    return spec


def extension_map() -> dict:
    mapping = {}
    for language, extensions in LANGUAGES.items():
        for extension in extensions:
            mapping.setdefault(extension, language)
    for name, entry in custom_specs().items():
        for extension in entry.get("extensions", []):
            mapping[extension] = name
    return mapping


def identify(filename: str) -> str:
    name = Path(str(filename)).name.lower()
    if name in ("dockerfile", "containerfile"):
        return "dockerfile"
    if name in ("cmakelists.txt",):
        return "cmake"
    return extension_map().get(Path(name).suffix.lower(), "plaintext")


def clean_env(extra: dict | None = None) -> dict:
    """Minimal child environment: secrets in the API process are not inherited."""
    allowed = (
        "PATH", "HOME", "USERPROFILE", "USER", "LOGNAME", "TMPDIR", "TMP", "TEMP",
        "LANG", "LC_ALL", "SYSTEMROOT", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE", "TERM", "SHELL",
    )
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "NO_COLOR": "1",
        "CI": "1",
    })
    if extra:
        for key, value in extra.items():
            if isinstance(key, str) and isinstance(value, str) and len(value) < 4096:
                env[key] = value
    return env


def _resolve_executable(probe, which):
    if not probe:
        return None
    name = probe[0]
    return which(name)


def _fill(template, values):
    return [str(part).format(**values) for part in template]


def _run_version(probe, which, run):
    exe = _resolve_executable(probe, which)
    if not exe:
        return None
    command = [exe] + [str(part).format(exe=exe, file="", out="", stem="")
                       for part in probe[1:]]
    try:
        result = run(command, cwd=Path(tempfile.gettempdir()), timeout=5)
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict):
        return None
    text = (result.get("stdout") or result.get("stderr") or "").strip()
    return text.splitlines()[0][:160] if text else None


def capability(language, *, which=shutil.which, run=None, use_cache=True) -> dict:
    run = run or run_argv
    name = normalize(language)
    spec = get_spec(name)
    extension = ""
    extensions = LANGUAGES.get(name)
    if extensions:
        extension = extensions[0]
    else:
        for extension_name, language_name in extension_map().items():
            if language_name == name:
                extension = extension_name
                break
    probes = spec.get("probes") or []
    executable = None
    version = None
    matched_probe = None
    if probes:
        for probe in probes:
            candidate = _resolve_executable(probe, which)
            if candidate:
                executable = candidate
                matched_probe = probe
                break
        if executable and use_cache:
            cached = _CACHE["value"] if time.monotonic() - float(_CACHE["at"]) < 30 else None
            if isinstance(cached, dict) and name in cached:
                version = cached[name]
        if executable and version is None and matched_probe:
            version = _run_version(matched_probe, which, run)
    missing = [required for required in spec.get("require", []) if not which(required)]
    requires_toolchain = bool(probes)
    available = (not requires_toolchain) or (executable is not None and not missing)
    actions = []
    if spec.get("check") or spec.get("compile"):
        actions.append("check")
    if (spec.get("compile") and spec.get("execute")) or spec.get("run"):
        actions.append("run")
    for action in ("test", "build"):
        if spec.get(action):
            actions.append(action)
    return {
        "language": name,
        "category": spec.get("category", "custom"),
        "custom": bool(spec.get("custom")),
        "installed": available,
        "requires_toolchain": requires_toolchain,
        "executable": executable,
        "version": version,
        "missing_executables": missing,
        "actions": actions,
        "default_file": spec.get("default_file"),
        "has_starter": bool(spec.get("hello")),
        "install_hint": spec.get("install", ""),
        "extension": extension,
    }


def report(*, which=shutil.which, run=None, use_cache=True) -> dict:
    names = sorted(set(SPECS) | set(custom_specs()))
    languages = [capability(name, which=which, run=run, use_cache=use_cache) for name in names]
    if use_cache:
        _CACHE["at"] = time.monotonic()
        _CACHE["value"] = {item["language"]: item["version"] for item in languages}
    return {
        "languages": languages,
        "language_count": len(languages),
        "installed_count": sum(1 for item in languages if item["installed"]),
        "execution": "argv-only, no shell; host toolchain opt-in",
    }


def reset_cache():
    _CACHE["at"] = 0.0
    _CACHE["value"] = None


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 400:
        raise ValueError("Target path is required")
    if unsafe_relative_path(value):
        raise ValueError("Target path must stay inside the workspace")
    path = Path(value)
    if any(part in (".agent", ".git") for part in path.parts):
        raise ValueError("Internal metadata paths are not executable targets")
    return path.as_posix()


def plan(language, action, *, target=None, out=None, executable=None,
         extra_args=None, timeout=None) -> dict:
    """Return the argv steps for an action without executing them."""
    spec = get_spec(language)
    name = spec["name"]
    action = str(action).lower()
    if action not in ("check", "run", "test", "build"):
        raise ValueError("Action must be check, run, test or build")
    if action in ("test", "build") and not spec.get(action):
        raise ValueError(f"{name} has no {action} command in the registry")
    if action in ("check", "run") and not target:
        raise ValueError("A target file is required for this action")
    relative = safe_relative(str(target)) if target else None
    exe = executable
    if exe is None:
        for probe in spec.get("probes") or []:
            found = shutil.which(probe[0])
            if found:
                exe = found
                break
    if spec.get("probes") and not exe:
        hint = spec.get("install") or "Install the toolchain and retry"
        raise ValueError(f"{name} toolchain is not installed. {hint}")
    values = {
        "exe": exe or "", "file": relative or "",
        "out": str(out) if out else "<temporary-build-dir>",
        "stem": Path(relative).stem if relative else "",
    }
    steps = []
    if action == "run":
        if spec.get("compile") and spec.get("execute"):
            steps.append(_fill(spec["compile"], values))
            steps.append(_fill(spec["execute"], values))
        elif spec.get("run"):
            steps.append(_fill(spec["run"], values))
        else:
            raise ValueError(f"{name} has no run command; use check or build")
    elif action == "check":
        if spec.get("check"):
            steps.append(_fill(spec["check"], values))
        elif spec.get("compile"):
            steps.append(_fill(spec["compile"], values))
        else:
            raise ValueError(f"{name} has no check command")
    else:
        steps.append(_fill(spec[action], values))
    if extra_args:
        if not isinstance(extra_args, list) or len(extra_args) > 16 or not all(
                isinstance(item, str) and len(item) <= 200 for item in extra_args):
            raise ValueError("extra_args must be at most 16 short strings")
        steps[-1] = steps[-1] + extra_args
    return {
        "language": name, "action": action, "executable": exe,
        "target": relative, "steps": steps,
        "timeout": max(5, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT)),
        "shell": False,
    }


def _validate_run_argv(argv):
    if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV:
        raise ValueError("Command must be a non-empty argv list")
    for part in argv:
        if not isinstance(part, str) or not part or len(part) > MAX_ARG_CHARS:
            raise ValueError("Command arguments must be short strings")
        if "\x00" in part or "\n" in part:
            raise ValueError("Command arguments cannot contain control characters")
    return argv


def _kill(process):
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def run_argv(argv, cwd, timeout=DEFAULT_TIMEOUT, env=None, stdin_text=None) -> dict:
    """Execute one argv list without a shell, with bounded output and timeout."""
    argv = _validate_run_argv(argv)
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise ValueError("Working directory does not exist")
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    popen_kwargs = {
        "cwd": str(cwd), "shell": False, "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE, "stdin": subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        "text": True, "encoding": "utf-8", "errors": "replace", "env": clean_env(env),
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    started = time.monotonic()
    process = subprocess.Popen(argv, **popen_kwargs)
    timed_out = False
    try:
        out, err = process.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(process)
        try:
            out, err = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", "Process did not exit after termination"
    return {
        "argv": argv,
        "exit_code": int(process.returncode if process.returncode is not None else 124),
        "stdout": (out or "")[-MAX_OUTPUT:],
        "stderr": (err or "")[-MAX_STDERR:],
        "timed_out": timed_out,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "timeout_seconds": timeout,
    }


def execute(language, action, root, *, target=None, extra_args=None,
            timeout=None, env=None, runner=None) -> dict:
    """Plan and run an action inside ``root``. Returns every step's result."""
    runner = runner or run_argv
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Workspace does not exist")
    out = Path(tempfile.mkdtemp(prefix="polyglot-build-"))
    try:
        steps = plan(language, action, target=target, out=out,
                     extra_args=extra_args, timeout=timeout)
        results = []
        for argv in steps["steps"]:
            result = runner(argv, cwd=root, timeout=steps["timeout"], env=env)
            results.append(result)
            if result.get("exit_code", 1) != 0 or result.get("timed_out"):
                break
        passed = all(result.get("exit_code") == 0 and not result.get("timed_out")
                     for result in results) and len(results) == len(steps["steps"])
        return {
            "language": steps["language"], "action": steps["action"],
            "passed": passed, "steps": results,
            "exit_code": results[-1]["exit_code"] if results else 1,
            "shell": False,
        }
    finally:
        shutil.rmtree(out, ignore_errors=True)


def project_languages(root, *, max_files=5000) -> dict:
    root = Path(root).resolve()
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    seen = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not (Path(base) / name).is_symlink()]
        for name in files:
            path = Path(base) / name
            if path.is_symlink():
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            seen += 1
            if seen > max_files:
                break
            language = identify(name)
            if language == "plaintext":
                continue
            counts[language] = counts.get(language, 0) + 1
            bucket = samples.setdefault(language, [])
            if len(bucket) < 5:
                bucket.append(path.relative_to(root).as_posix())
        if seen > max_files:
            break
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "files_scanned": seen,
        "languages": [{"language": language, "files": count, "samples": samples.get(language, [])}
                      for language, count in ordered],
        "total_coded_files": sum(counts.values()),
    }


def scaffold(language) -> dict:
    spec = get_spec(language)
    default_file = spec.get("default_file")
    hello = spec.get("hello")
    if not default_file or not hello:
        raise ValueError(f"{spec['name']} has no starter template; register one or create the file manually")
    files = {default_file: hello}
    files.update(MANIFESTS.get(spec["name"], {}))
    return files


KEYWORDS = [
    (("react", "next.js", "node", "express", "npm", "javascript", "browser", "frontend"), "javascript"),
    (("typescript", "type-safe", "tsx", ".ts"), "typescript"),
    (("rust", "cargo", "borrow checker"), "rust"),
    (("golang", "go lang", "goroutine"), "go"),
    (("python", "django", "flask", "pandas", "numpy", "script"), "python"),
    (("java ", "spring", "jvm"), "java"),
    (("kotlin", "android"), "kotlin"),
    (("swift", "ios", "macos"), "swift"),
    (("c#", "csharp", ".net", "dotnet", "unity"), "csharp"),
    (("c++", "cpp", "template metaprogramming"), "cpp"),
    (("c program", "c language", "embedded", "microcontroller"), "c"),
    (("ruby", "rails"), "ruby"),
    (("php", "laravel"), "php"),
    (("sql", "database", "query", "postgres", "mysql", "sqlite"), "sql"),
    (("html", "page", "website layout"), "html"),
    (("css", "stylesheet", "layout styling"), "css"),
    (("bash", "shell script", "terminal command"), "shell"),
    (("powershell", "windows script"), "powershell"),
    (("haskell", "functional"), "haskell"),
    (("elixir", "phoenix"), "elixir"),
    (("lua", "roblox"), "lua"),
    (("dart", "flutter"), "dart"),
    (("zig",), "zig"),
    (("solidity", "smart contract", "ethereum"), "solidity"),
    (("verilog", "fpga", "hardware description"), "verilog"),
]


def guess_language(text: str, *, default="python") -> str:
    lowered = " " + str(text or "").lower() + " "
    for needles, language in KEYWORDS:
        if any(needle in lowered for needle in needles):
            return language
    return default


def choose_language(instruction, explicit=None, project_root=None,
                    *, which=shutil.which) -> dict:
    if explicit and normalize(str(explicit)) not in ("auto", "any", ""):
        name = normalize(str(explicit))
        get_spec(name)
        return {"language": name, "reason": "explicit"}
    if project_root and Path(project_root).is_dir():
        breakdown = project_languages(project_root)
        for item in breakdown["languages"]:
            info = capability(item["language"], which=which)
            if info["installed"] and item["language"] != "plaintext":
                return {"language": item["language"], "reason": "dominant project language"}
    guessed = guess_language(instruction)
    if capability(guessed, which=which)["installed"]:
        return {"language": guessed, "reason": "instruction keywords"}
    for name in ("python", "javascript", "shell", "c"):
        if capability(name, which=which)["installed"]:
            return {"language": name, "reason": "first installed fallback"}
    return {"language": guessed, "reason": "no toolchain installed"}
