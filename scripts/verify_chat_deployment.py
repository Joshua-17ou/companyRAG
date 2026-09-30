"""Exercise the deployed SSE endpoint through nginx, using one disposable test session."""
import argparse
import json
from pathlib import Path
import re
import requests


BASE = "http://127.0.0.1:3000"


def check_stream(query, hospital=None, user_dept="销售", session_id=None, no_results=False):
    params = {"question": query, "enable_intent": "true", "user_dept": user_dept}
    if session_id:
        params["session_id"] = session_id
    with requests.post(f"{BASE}/api/qa/stream", params=params, stream=True, timeout=(10, 120)) as response:
        response.raise_for_status()
        assert "text/event-stream" in response.headers["Content-Type"]
        response.encoding = "utf-8"
        events = [json.loads(line[6:]) for line in response.iter_lines(decode_unicode=True) if line.startswith("data: ")]
    assert events[-1]["type"] == "done", events
    assert not any(event["type"] == "error" for event in events), events
    answer = next(event for event in events if event["type"] == "answer")
    assert answer["content"].strip(), events
    sources = answer.get("sources", [])
    if hospital:
        assert sources, answer
        assert all(source.get("hospital") == hospital for source in sources), sources
    if no_results:
        assert not sources and "未找到" in answer["content"], answer
    images = answer.get("images", [])
    if images:
        image_response = requests.get(BASE + images[0]["url"], timeout=15)
        image_response.raise_for_status()
        assert image_response.headers["Content-Type"].startswith("image/")
    print(json.dumps({"query": query, "user_dept": user_dept, "answer_chars": len(answer["content"]),
                      "preview": answer["content"][:100], "hospitals": [source.get("hospital") for source in sources],
                      "images": len(images), "status": "PASS"}, ensure_ascii=False), flush=True)
    return answer


def main():
    index = requests.get(BASE, timeout=10)
    index.raise_for_status()
    for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.text):
        deployed = requests.get(BASE + asset, timeout=15)
        deployed.raise_for_status()
        assert deployed.content == (Path("frontend/dist") / asset.lstrip("/")).read_bytes(), asset
    print("Frontend compiled assets match deployment", flush=True)
    created = requests.post(f"{BASE}/api/sessions", params={"user_dept": "销售", "title": "自动回归验证-完成后删除"}, timeout=15)
    created.raise_for_status()
    session_id = created.json()["session"]["id"]
    try:
        check_stream("hello", session_id=session_id)
        saved = requests.get(f"{BASE}/api/sessions/{session_id}", timeout=15)
        saved.raise_for_status()
        messages = saved.json()["messages"]
        assert len(messages) == 2 and messages[-1]["content"].strip(), messages
        check_stream("你好")
        check_stream("spd功能")
        check_stream("肇庆市一spd流程", hospital="肇庆市一")
        check_stream("肇庆市二spd流程", hospital="肇庆市二")
        check_stream("肇庆市一spd流程", user_dept="行政", no_results=True)
        check_stream("火星量子传送门维修说明", no_results=True)
    finally:
        deleted = requests.delete(f"{BASE}/api/sessions/{session_id}", timeout=15)
        deleted.raise_for_status()
        print("Disposable test session removed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-model", action="store_true",
                        help="Allow the configured external model to receive test queries and retrieved internal SPD text/image references")
    args = parser.parse_args()
    if not args.allow_external_model:
        parser.error("Explicit --allow-external-model consent is required before transmitting internal knowledge-base excerpts")
    main()
