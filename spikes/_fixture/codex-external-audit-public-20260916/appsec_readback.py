#!/usr/bin/env python3
"""CI-only readback of the SourceCraft AppSec report artifact."""
import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

PROTO = '''syntax = "proto3"; package v1.results;
service FileDownloadService { rpc DownloadFileStream(FileDownloadRequest) returns (stream DownloadFileStreamResponse); }
message FileDownloadRequest { string git_repo=1; string commit=2; string engine_name=3; int32 type=4; string repo_public_uuid=5; optional string scan_id=6; optional string scan_uuid=7; }
message DownloadFileStreamResponse { bytes content=1; }'''
NAMESPACE = uuid.UUID("cc306167-a757-42f9-b41b-ca77e6b4723b")


def stubs():
    from grpc_tools import protoc
    with tempfile.TemporaryDirectory(prefix="sc-proto-") as d:
        p = Path(d) / "download.proto"
        p.write_text(PROTO, encoding="utf-8")
        if protoc.main(["protoc", f"-I{d}", f"--python_out={d}", f"--grpc_python_out={d}", str(p)]) != 0:
            raise RuntimeError("protoc failed")
        sys.path.insert(0, d)
        import download_pb2
        import download_pb2_grpc
        download_pb2._keepalive = d
        return download_pb2, download_pb2_grpc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("sast", "sca", "secrets"))
    ap.add_argument("engine")
    args = ap.parse_args()
    import grpc
    pb2, grpc_mod = stubs()
    token = os.environ["SOURCECRAFT_TOKEN"]
    auth = token if token.lower().startswith("bearer ") else "Bearer " + token
    repo_id = os.environ["SOURCECRAFT_REPO_ID"]
    scan_id = str(uuid.uuid5(NAMESPACE, f"{repo_id}:{os.environ['SOURCECRAFT_RUN_ID']}"))
    request = pb2.FileDownloadRequest(
        git_repo="",
        commit=os.environ["SOURCECRAFT_COMMIT_SHA"],
        engine_name=args.engine,
        type=2 if args.kind == "sca" else 1,
        repo_public_uuid=repo_id,
        scan_uuid=scan_id,
    )
    last_code = "UNKNOWN"
    for attempt in range(12):
        try:
            channel = grpc.secure_channel("appsec.sourcecraft.tech:443", grpc.ssl_channel_credentials())
            raw = b"".join(
                bytes(chunk.content)
                for chunk in grpc_mod.FileDownloadServiceStub(channel).DownloadFileStream(
                    request, metadata=(("authorization", auth),), timeout=60
                )
            )
            channel.close()
            payload = json.loads(raw.decode("utf-8"))
            records = payload.get("packages", []) if args.kind == "sca" else [r for run in payload.get("runs", []) for r in run.get("results", [])]
            sample = records[0] if records else {}
            if args.kind != "sca":
                sample = {k: sample.get(k) for k in ("ruleId", "level", "message", "locations", "baselineState")}
            else:
                sample = {k: sample.get(k) for k in ("name", "versionInfo", "SPDXID", "licenseConcluded")}
            print(json.dumps({"kind": args.kind, "transport": "SourceCraft FileDownloadService", "bytes": len(raw), "records": len(records), "sample": sample}, ensure_ascii=False))
            return 0
        except grpc.RpcError as exc:
            last_code = exc.code().name
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            last_code = type(exc).__name__
        if attempt < 11:
            time.sleep(5)
    print(json.dumps({"kind": args.kind, "status": "ERROR", "grpc_code": last_code}))
    return 1


raise SystemExit(main())
