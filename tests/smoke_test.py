"""端到端冒烟测试：不依赖第三方库，直接调用 mime.py。"""
import base64
import sys

sys.path.insert(0, ".")
from app import diff, mime

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def roundtrip(raw_b, **kw):
    """raw_b 为 bytes；按 UTF-8 解码成 JSON 文本后传入（模拟浏览器）。"""
    r = mime.parse_message(raw_b.decode("utf-8"), kw.get("ct"), kw.get("boundary"))
    assert r["ok"], r
    enc = mime.encode_tree(r["tree"], include_headers=kw.get("include_headers", True))
    assert enc["ok"], enc["issues"]
    return r, enc, base64.b64decode(enc["payloadBase64"])


# 1. 基本 multipart/form-data，含 CJK 与 quoted boundary --------------------
print("1) 基本 form-data 往返")
raw = (
    b'Content-Type: multipart/form-data; boundary="----B"\r\n'
    b'\r\n'
    b'------B\r\n'
    b'Content-Disposition: form-data; name="u"\r\n'
    b'\r\n'
    b'alice\r\n'
    b'------B\r\n'
    b'Content-Disposition: form-data; name="bio"\r\n'
    b'\r\n'
    + "你好".encode() + b'\r\n'
    b'------B--'
)
r, enc, out = roundtrip(raw)
check("顶层是 multipart", r["tree"]["kind"] == "multipart")
check("2 个子部分", len(r["tree"]["parts"]) == 2)
check("boundary 去引号生效", r["effectiveBoundary"] == "----B")
check("part name 解析", r["tree"]["parts"][0]["name"] == "u")
check("CJK 往返", "你好".encode() in out)
check("无 error", r["counts"]["error"] == 0, r["issues"])
check("重新编码包含关闭定界符", b"------B--" in out)
# 参数引号会被规范化（合法 token 去引号），故比较规范化后的形式
canonical_raw = raw.replace(b'boundary="----B"', b"boundary=----B")
check("字节级往返一致（参数引号规范化）", out == canonical_raw,
      f"\n{out!r}\n!=\n{canonical_raw!r}")

# 2. 嵌套 multipart（含 preamble / epilogue） -------------------------------
print("2) 嵌套 multipart")
raw2 = (
    b'Content-Type: multipart/mixed; boundary=OUTER\r\n\r\n'
    b'preamble text\r\n'
    b'--OUTER\r\n'
    b'Content-Type: text/plain\r\n\r\n'
    b'outer body\r\n'
    b'--OUTER\r\n'
    b'Content-Type: multipart/alternative; boundary="INNER42"\r\n\r\n'
    b'nested preamble\r\n'
    b'--INNER42\r\nContent-Type: text/plain\r\n\r\nplain\r\n'
    b'--INNER42\r\nContent-Type: text/html\r\n\r\n<b>html</b>\r\n'
    b'--INNER42--\r\n'
    b'--OUTER\r\nContent-Type: text/csv\r\n\r\na,b\r\n1,2\r\n'
    b'--OUTER--\r\n'
    b'epi'
)
r2, enc2, out2 = roundtrip(raw2)
t = r2["tree"]
check("3 个外层部分", len(t["parts"]) == 3, [(p["kind"], p.get("mediaType")) for p in t["parts"]])
nested = t["parts"][1]
check("第 2 部分识别为嵌套 multipart", nested["kind"] == "multipart"
      and nested["mediaType"] == "multipart/alternative")
check("嵌套 2 部分", len(nested["parts"]) == 2)
check("preamble 保留", "preamble text" in t["preamble"])
check("嵌套 preamble 保留", "nested preamble" in nested["preamble"])
check("epilogue 保留", t["epilogue"] == "epi", repr(t["epilogue"]))
check("嵌套往返一致", out2 == raw2.replace(b'boundary="INNER42"', b"boundary=INNER42"),
      f"\n{out2!r}\n!=\n{raw2!r}")
check("嵌套无 error", r2["counts"]["error"] == 0,
      [i for i in r2["issues"] if i["level"] == "error"])

# 3. LF 规范化 + 缺关闭定界符 + 畸形 header ---------------------------------
print("3) 错误报文诊断")
raw3 = (
    b'Content-Type: multipart/form-data; boundary=X\n'
    b'\n'
    b'--X\nContent-Disposition: form-data; name="ok"\n\ngood\n'
    b'--X\nBroken Header Line no colon\n\nrest'
)
r3 = mime.parse_message(raw3.decode(), None, None)
codes = [i["code"] for i in r3["issues"]]
check("检测到 LF 规范化", "LF_NORMALIZED" in codes, codes)
# 首行不是合法字段 => 该部分无有效头部块
check("畸形头部报错", "NO_HEADER_BODY_SEPARATOR" in codes, codes)
check("缺少关闭定界符报错", "MISSING_CLOSE_DELIMITER" in codes, codes)

# 3b. 首行合法、次行畸形 -> BAD_HEADER_LINE
raw3b = (
    b"Content-Type: multipart/mixed; boundary=Y\r\n\r\n"
    b"--Y\r\nGood-Header: yes\r\nbroken line without colon\r\n\r\nbody\r\n--Y--"
)
r3b = mime.parse_message(raw3b.decode(), None, None)
check("首行合法时次行畸形报 BAD_HEADER_LINE",
      any(i["code"] == "BAD_HEADER_LINE" for i in r3b["issues"]),
      [i["code"] for i in r3b["issues"]])
check("仍尽力恢复 2 个部分", len(r3["tree"]["parts"]) == 2)
enc3 = mime.encode_tree(r3["tree"], include_headers=True)
check("重新编码总是生成关闭定界符",
      b"--X--" in base64.b64decode(enc3["payloadBase64"]))

# 4. boundary 输入框覆盖 + body-only ----------------------------------------
print("4) boundary 覆盖与无头部 body")
body_only = b"--CUSTOM\r\nContent-Type: text/plain\r\n\r\nv\r\n--CUSTOM--"
r4 = mime.parse_message(body_only.decode(), None, "CUSTOM")
check("无顶层头部按 body 解析", r4["hasTopHeaders"] is False)
check("输入框 boundary 生效", r4["effectiveBoundary"] == "CUSTOM")
check("无 error", r4["counts"]["error"] == 0, r4["issues"])
enc4 = mime.encode_tree(r4["tree"], include_headers=False)
out4 = base64.b64decode(enc4["payloadBase64"])
check("仅输出 body 时不含顶层头部", not out4.startswith(b"Content-Type"), out4[:60])
check("body-only 往返一致", out4 == body_only, f"\n{out4!r}\n!=\n{body_only!r}")

# 5. quoted 参数带转义 ------------------------------------------------------
print("5) quoted-string 参数解析")
issues5 = []
mt, p = mime.parse_content_type(
    'multipart/form-data; boundary="ABC.123_-"; charset="utf\\"-8"; x=tok',
    issues5)
check("quoted boundary 保留", p.get("boundary") == "ABC.123_-", p)
check("反斜杠转义引号", p.get("charset") == 'utf"-8', p)
check("普通 token 参数", p.get("x") == "tok")
check("无解析 issue", issues5 == [], issues5)

# 6. 边界碰撞：正文中的 "--Z" 不在行首或无 CRLF 后缀 ------------------------
print("6) 正文中包含类似 boundary 的文本")
body6 = (
    b"--Z\r\nContent-Type: text/plain\r\n\r\nfake --Zline\r\n--Z\r\n"
    b"Content-Type: text/plain\r\n\r\nsecond\r\n--Z--"
)
r6 = mime.parse_message(body6.decode(), "multipart/mixed", "Z")
check("碰撞文本未被误判为定界符", len(r6["tree"]["parts"]) == 2,
      [i["message"] for i in r6["issues"]])
check("第一部分正文完整", r6["tree"]["parts"][0]["body"] == "fake --Zline")
check("碰撞无 error", r6["counts"]["error"] == 0, r6["issues"])

# 7. 修改后再编码 -----------------------------------------------------------
print("7) 编辑后重新编码")
r7 = mime.parse_message(raw.decode(), None, None)
r7["tree"]["parts"][0]["body"] = "bob"
r7["tree"]["boundary"] = "NEW-B"
enc7 = mime.encode_tree(r7["tree"], include_headers=True)
out7 = base64.b64decode(enc7["payloadBase64"])
check("使用新 boundary", b"--NEW-B\r\n" in out7 and b"--NEW-B--" in out7)
check("Content-Type 头 boundary 同步", b"boundary=NEW-B" in out7, out7[:120])
check("正文更新", b"\r\nbob\r\n--NEW-B" in out7)
check("旧 boundary 不再出现", b"----B" not in out7)

# 8. 非 UTF-8 二进制正文逐字节保持 ------------------------------------------
print("8) 非 UTF-8 正文逐字节保持")
binary = bytes(range(1, 256))
raw8 = (b"Content-Type: multipart/mixed; boundary=BIN\r\n\r\n"
        b"--BIN\r\n\r\n" + binary + b"\r\n--BIN--")
r8 = mime.parse_message(None, None, None, raw_base64=base64.b64encode(raw8).decode())
check("二进制正文标记 base64", r8["tree"]["parts"][0]["bodyEncoding"] == "base64")
# 无头部部分：分隔定界符行后的前导 CRLF 是正文的一部分
check("base64 载荷正确", base64.b64decode(r8["tree"]["parts"][0]["body"]) == b"\r\n" + binary)
enc8 = mime.encode_tree(r8["tree"], True)
out8 = base64.b64decode(enc8["payloadBase64"])
check("二进制字节级往返", out8 == raw8, "二进制损坏")

# 9. 异常输入不崩溃 ---------------------------------------------------------
print("9) 异常输入不崩溃")
r9 = mime.parse_message("garbage without delimiters", "multipart/mixed", "NOPE")
check("找不到定界符报错且不崩", any(i["code"] == "NO_DELIMITER" for i in r9["issues"]))
r10 = mime.parse_message("", None, None)
check("空输入返回结构", "tree" in r10 or r10.get("ok") is False)

# 10. body 无头部、有 preamble 的 body-only ---------------------------------
print("10) 仅 body 且带 preamble")
raw10 = b"hi this is preamble\r\n--P\r\n\r\nbody\r\n--P--\r\ntail"
r10p = mime.parse_message(raw10.decode(), "multipart/mixed", "P")
check("preamble 识别", r10p["tree"]["preamble"] == "hi this is preamble",
      repr(r10p["tree"]["preamble"]))
check("epilogue 识别", r10p["tree"]["epilogue"] == "tail", repr(r10p["tree"]["epilogue"]))
enc10 = mime.encode_tree(r10p["tree"], include_headers=False)
out10 = base64.b64decode(enc10["payloadBase64"])
check("body-only 带序言往返", out10 == raw10, f"\n{out10!r}\n!=\n{raw10!r}")

# 11. 样本对比：媒体类型 / 头部 / 正文 / boundary / 序言 / 诊断 --------------
print("11) 样本对比 diff_results")
rawA = (
    b'Content-Type: multipart/mixed; boundary=AA\r\n\r\n'
    b'pre\r\n'
    b'--AA\r\nContent-Type: text/plain\r\n\r\nhello\r\n'
    b'--AA\r\nContent-Type: text/html\r\nX-Extra: 1\r\n\r\n<b>hi</b>\r\n'
    b'--AA--\r\nepi'
)
rawB = (
    b'Content-Type: multipart/mixed; boundary=BB\r\n\r\n'
    b'pre2\r\n'
    b'--BB\r\nContent-Type: text/plain\r\n\r\nhello\r\n'
    b'--BB\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<b>hi2</b>\r\n'
    b'--BB\r\nContent-Type: application/json\r\n\r\n{}\r\n'
    b'--BB--\r\nepi'
)
sa = mime.parse_message(rawA.decode(), None, None)
sb = mime.parse_message(rawB.decode(), None, None)
d = diff.diff_results({"tree": sa["tree"], "issues": sa["issues"]},
                      {"tree": sb["tree"], "issues": sb["issues"]})
check("diff ok", d["ok"] is True)
by_path = {e["path"]: e for e in d["entries"]}
check("新增 1 个部分", d["summary"]["added"] == 1, d["summary"])
check("无删除", d["summary"]["removed"] == 0, d["summary"])
check("parts[2] 标记为新增", by_path["parts[2]"]["change"] == "added")
check("parts[0] 完全一致", by_path["parts[0]"]["change"] == "unchanged")
root_fields = {f["field"] for f in by_path["root"]["fields"]}
check("root 检出 boundary 变化", "boundary" in root_fields, root_fields)
check("root 检出序言变化", "preamble" in root_fields, root_fields)
check("root 未误报尾注变化", "epilogue" not in root_fields, root_fields)
p1_fields = {f["field"]: f for f in by_path["parts[1]"]["fields"]}
check("parts[1] 检出正文变化", "body" in p1_fields, list(p1_fields))
check("parts[1] 检出头部变化", "headers" in p1_fields, list(p1_fields))
check("头部新增 Content-Type 行",
      any("charset" in l for l in p1_fields["headers"]["added"]),
      p1_fields["headers"])
check("头部删除 X-Extra 行",
      any(l.startswith("X-Extra") for l in p1_fields["headers"]["removed"]),
      p1_fields["headers"])
check("正文预览带长度", p1_fields["body"]["b"]["length"] == len("<b>hi2</b>"))

# 11b. 反向对比：新增变删除；诊断代码差异 ------------------------------------
d2 = diff.diff_results({"tree": sb["tree"], "issues": sb["issues"]},
                       {"tree": sa["tree"], "issues": sa["issues"]})
by_path2 = {e["path"]: e for e in d2["entries"]}
check("反向 parts[2] 标记为删除", by_path2["parts[2]"]["change"] == "removed")
check("反向 summary 删除 1", d2["summary"]["removed"] == 1, d2["summary"])

rawC = (b'Content-Type: multipart/mixed; boundary=AA\r\n\r\n'
        b'--AA\r\nContent-Type: text/plain\r\n\r\nhello\r\n'
        b'--AA\r\nContent-Type: text/html\r\nX-Extra: 1\r\n\r\n<b>hi</b>\r\n'
        b'--AA--')
sc = mime.parse_message(rawC.decode(), None, None)
check("rawC 有序言诊断", any(i["code"] == "PREAMBLE" for i in sa["issues"]))
d3 = diff.diff_results({"tree": sa["tree"], "issues": sa["issues"]},
                       {"tree": sc["tree"], "issues": sc["issues"]})
by_path3 = {e["path"]: e for e in d3["entries"]}
root_issue_field = next((f for f in by_path3["root"]["fields"]
                         if f["field"] == "issues"), None)
check("root 检出诊断代码差异", root_issue_field is not None,
      by_path3["root"]["fields"])
check("PREAMBLE 仅存在于 A", root_issue_field
      and "PREAMBLE" in root_issue_field["removed"], root_issue_field)

# 11c. 嵌套子树整体删除折叠为一条；全局诊断 -----------------------------------
rawD = (
    b'Content-Type: multipart/mixed; boundary=O\r\n\r\n'
    b'--O\r\nContent-Type: text/plain\r\n\r\nkeep\r\n'
    b'--O\r\nContent-Type: multipart/alternative; boundary=I\r\n\r\n'
    b'--I\r\nContent-Type: text/plain\r\n\r\np\r\n'
    b'--I\r\nContent-Type: text/html\r\n\r\nh\r\n'
    b'--I--\r\n'
    b'--O--'
)
rawE = (b'Content-Type: multipart/mixed; boundary=O\r\n\r\n'
        b'--O\r\nContent-Type: text/plain\r\n\r\nkeep\r\n'
        b'--O--')
sd_ = mime.parse_message(rawD.decode(), None, None)
se = mime.parse_message(rawE.decode(), None, None)
d4 = diff.diff_results({"tree": sd_["tree"], "issues": sd_["issues"]},
                       {"tree": se["tree"], "issues": se["issues"]})
removed_entries = [e for e in d4["entries"] if e["change"] == "removed"]
check("嵌套子树删除折叠为 1 条", len(removed_entries) == 1,
      [(e["path"], e["change"]) for e in d4["entries"]])
check("删除摘要带后代数量",
      removed_entries[0]["summary"]["descendantParts"] == 2,
      removed_entries[0]["summary"])

rawF = rawE.replace(b"\r\n", b"\n")  # 全 LF -> 触发全局 LF_NORMALIZED
sf = mime.parse_message(rawF.decode("utf-8"), None, None)
d5 = diff.diff_results({"tree": se["tree"], "issues": se["issues"]},
                       {"tree": sf["tree"], "issues": sf["issues"]})
global_entries = [e for e in d5["entries"] if e["path"] == ""]
check("全局诊断差异单列一条", len(global_entries) == 1,
      [(e["path"], e["change"]) for e in d5["entries"]])
check("LF_NORMALIZED 为新增诊断",
      "LF_NORMALIZED" in global_entries[0]["fields"][0]["added"],
      global_entries[0]["fields"])

# 11d. 完全相同 -> 全部 unchanged ---------------------------------------------
d6 = diff.diff_results({"tree": sa["tree"], "issues": sa["issues"]},
                       {"tree": sa["tree"], "issues": sa["issues"]})
check("自比无差异", d6["summary"]["modified"] == 0
      and d6["summary"]["added"] == 0 and d6["summary"]["removed"] == 0,
      d6["summary"])
check("自比全部 unchanged", d6["summary"]["unchanged"] == len(d6["entries"]))

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)