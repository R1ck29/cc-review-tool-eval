#!/usr/bin/env python3
"""Measure the fixed cost an MCP server adds to *every* request.

An MCP server's tool definitions (name + description + JSON schema for each
tool) are injected into the system prompt of every request for the whole
session. That is a fixed tax paid before any work happens, and it is invisible
in per-query context measurements - which is why a tool that "reduces context"
can still increase total spend.

Speaks MCP over stdio and counts the tokens of the tools/list response.
"""
import json
import subprocess
import sys


def est_tokens(text):
    return (len(text) + 3) // 4


def list_tools(cmd, cwd=None):
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, cwd=cwd, bufsize=1)
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "bench", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    try:
        for m in msgs:
            proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
        for _ in range(80):
            line = proc.stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == 2:
                return obj["result"]["tools"]
    finally:
        proc.kill()
    return []


def main():
    tools = list_tools(sys.argv[1:])
    if not tools:
        print("no tools returned")
        return

    # What the model actually sees: name, description and the input schema.
    total = 0
    rows = []
    for t in tools:
        blob = json.dumps({"name": t.get("name"),
                           "description": t.get("description", ""),
                           "input_schema": t.get("inputSchema", {})})
        n = est_tokens(blob)
        total += n
        rows.append((t.get("name", "?"), n))

    rows.sort(key=lambda r: -r[1])
    print(f"{len(tools)} tools, {total:,} est. tokens of definitions\n")
    print("heaviest:")
    for name, n in rows[:8]:
        print(f"  {n:>6,}  {name}")
    print(f"\nfixed overhead per request while this server is connected: {total:,} tokens")


if __name__ == "__main__":
    main()
