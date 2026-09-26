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

# 12. Content-Transfer-Encoding：base64 / quoted-printable ------------------
print("12) Content-Transfer-Encoding 语义")

# 12a. base64 解码为可编辑内容；非规范折行的原始载荷未编辑时逐字节保留
b64 = base64.b64encode("你好，base64！".encode()).decode()
raw12 = ("Content-Type: multipart/mixed; boundary=E1\r\n\r\n"
         "--E1\r\nContent-Type: text/plain; charset=utf-8\r\n"
         "Content-Transfer-Encoding: base64\r\n\r\n"
         + b64[:8] + "\r\n" + b64[8:] + "\r\n--E1--").encode()
r12, enc12, out12 = roundtrip(raw12)
p12 = r12["tree"]["parts"][0]
check("识别 base64 CTE", p12["cte"] == "base64")
check("base64 解码成功", p12["cteDecoded"] is True)
check("解码为可编辑文本", p12["body"] == "你好，base64！", repr(p12["body"]))
check("保存原始载荷", base64.b64decode(
    p12["cteRaw"]) == (b64[:8] + "\r\n" + b64[8:]).encode()
    if p12["cteRawEncoding"] == "base64"
    else p12["cteRaw"] == b64[:8] + "\r\n" + b64[8:])
check("未编辑字节稳定（保留原始折行）", out12 == raw12,
      f"\n{out12!r}\n!=\n{raw12!r}")

# 12b. 编辑后重新编码：base64 按 76 列折行且可解码回新内容
r12b = mime.parse_message(raw12.decode(), None, None)
r12b["tree"]["parts"][0]["body"] = "长内容" * 100
out12b = base64.b64decode(
    mime.encode_tree(r12b["tree"], True)["payloadBase64"])
seg = out12b.split(b"--E1\r\n", 1)[1].rsplit(b"\r\n--E1--", 1)[0]
payload = seg.split(b"\r\n\r\n", 1)[1]
lines = payload.split(b"\r\n")
check("base64 重新编码折行 <= 76", all(len(l) <= 76 for l in lines),
      [len(l) for l in lines])
check("base64 折行为 76 列", len(lines[0]) == 76)
check("base64 重新编码内容正确",
      base64.b64decode(b"".join(lines)) == "长内容".encode() * 100)

# 12c. quoted-printable 解码与字节稳定
raw12c = (b"--E\r\nContent-Type: text/plain\r\n"
          b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
          b"caf=C3=A9 =3D ok=20\r\n--E--")
r12c = mime.parse_message(raw12c.decode(), "multipart/mixed", "E")
p12c = r12c["tree"]["parts"][0]
check("识别 QP CTE", p12c["cte"] == "quoted-printable")
check("QP 解码为文本", p12c["cteDecoded"] is True
      and p12c["body"] == "café = ok ", repr(p12c["body"]))
out12c = base64.b64decode(
    mime.encode_tree(r12c["tree"], False)["payloadBase64"])
check("QP 未编辑字节稳定", out12c == raw12c, f"\n{out12c!r}\n!=\n{raw12c!r}")

# 12d. QP 重新编码：76 列软换行、行尾空白编码、往返一致
src = ("A" * 200 + "  \n" + "中文 = 测试").encode()
enc_qp = mime._encode_qp_transport(src)
dec_qp, bad_qp = mime._decode_qp_transport(enc_qp)
check("QP 编码每行 <= 76", all(len(l) <= 76 for l in enc_qp.split(b"\r\n")))
check("QP 行尾空白被编码", b"=20=20\r\n" in enc_qp, enc_qp[-60:])
check("QP 编码往返一致", dec_qp == src.replace(b"\n", b"\r\n") and bad_qp == 0)

# 12e. 畸形 base64：带节点路径的诊断 + 原始载荷不丢失 + 字节稳定
raw12e = (b"Content-Type: multipart/mixed; boundary=O\r\n\r\n"
          b"--O\r\nContent-Type: text/plain\r\n\r\nkeep\r\n"
          b"--O\r\nContent-Type: multipart/mixed; boundary=I\r\n\r\n"
          b"--I\r\nContent-Transfer-Encoding: base64\r\n\r\n"
          b"SGVsbG8@###==\r\n--I--\r\n--O--")
r12e = mime.parse_message(raw12e.decode(), None, None)
bad_issues = [i for i in r12e["issues"] if i["code"] == "CTE_BASE64_INVALID"]
check("畸形 base64 产生诊断", len(bad_issues) == 1, r12e["issues"])
check("诊断带节点路径", bad_issues
      and bad_issues[0]["message"].startswith("parts[1].parts[0]："),
      bad_issues)
p12e = r12e["tree"]["parts"][1]["parts"][0]
check("畸形 base64 未标记解码", p12e["cteDecoded"] is False)
check("畸形 base64 正文即原始载荷", p12e["body"] == "SGVsbG8@###==")
out12e = base64.b64decode(
    mime.encode_tree(r12e["tree"], True)["payloadBase64"])
check("畸形 base64 字节稳定", out12e == raw12e,
      f"\n{out12e!r}\n!=\n{raw12e!r}")

# 12f. 畸形 QP：warning + 畸形序列保留
raw12f = (b"--E\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
          b"abc=XY=Zdef\r\n--E--")
r12f = mime.parse_message(raw12f.decode(), "multipart/mixed", "E")
p12f = r12f["tree"]["parts"][0]
check("畸形 QP 产生 warning 诊断",
      any(i["code"] == "CTE_QP_INVALID" and i["level"] == "warning"
          and i["message"].startswith("parts[0]：") for i in r12f["issues"]),
      r12f["issues"])
check("畸形 QP 序列保留", p12f["body"] == "abc=XY=Zdef", repr(p12f["body"]))

# 12g. 未知 CTE / 7bit 违规 / multipart 上的编码
raw12g = (b"--E\r\nContent-Transfer-Encoding: x-uue\r\n\r\nbegin 644 x\r\n--E--")
r12g = mime.parse_message(raw12g.decode(), "multipart/mixed", "E")
check("未知 CTE 诊断", any(i["code"] == "CTE_UNKNOWN" for i in r12g["issues"]))
check("未知 CTE 按未编码处理", r12g["tree"]["parts"][0]["body"] == "begin 644 x")
out12g = base64.b64decode(
    mime.encode_tree(r12g["tree"], False)["payloadBase64"])
check("未知 CTE 字节稳定", out12g == raw12g)

raw12h = (b"--E\r\nContent-Transfer-Encoding: 7bit\r\n\r\ncaf\xc3\xa9\r\n--E--")
r12h = mime.parse_message(raw12h.decode(), "multipart/mixed", "E")
check("7bit 高位字节诊断",
      any(i["code"] == "CTE_7BIT_VIOLATION" for i in r12h["issues"]))

raw12i = (b"--E\r\nContent-Type: multipart/mixed; boundary=I\r\n"
          b"Content-Transfer-Encoding: base64\r\n\r\n"
          b"--I\r\n\r\nx\r\n--I--\r\n--E--")
r12i = mime.parse_message(raw12i.decode(), "multipart/mixed", "E")
check("multipart 上的 base64 诊断",
      any(i["code"] == "CTE_ON_MULTIPART" for i in r12i["issues"]))

# 12j. 切换编码方式（模拟前端下拉：改头部后按新声明回写）
r12j = mime.parse_message(raw12.decode(), None, None)
hdr = next(h for h in r12j["tree"]["parts"][0]["headers"]
           if h["name"].lower() == "content-transfer-encoding")
hdr["value"] = "quoted-printable"
out12j = base64.b64decode(
    mime.encode_tree(r12j["tree"], True)["payloadBase64"])
seg = out12j.split(b"--E1\r\n", 1)[1].rsplit(b"\r\n--E1--", 1)[0]
payload = seg.split(b"\r\n\r\n", 1)[1]
check("切换为 QP 后按 QP 回写",
      mime._decode_qp_transport(payload)[0] == "你好，base64！".encode(),
      payload)
check("QP 回写不含裸高位字节", all(b < 0x80 for b in payload))

# 反向：QP -> base64
r12k = mime.parse_message(raw12c.decode(), "multipart/mixed", "E")
hdr = next(h for h in r12k["tree"]["parts"][0]["headers"]
           if h["name"].lower() == "content-transfer-encoding")
hdr["value"] = "base64"
out12k = base64.b64decode(
    mime.encode_tree(r12k["tree"], False)["payloadBase64"])
seg = out12k.split(b"--E\r\n", 1)[1].rsplit(b"\r\n--E--", 1)[0]
payload = seg.split(b"\r\n\r\n", 1)[1]
check("切换为 base64 后按 base64 回写",
      base64.b64decode(payload) == "café = ok ".encode(), payload)

# 12k. diff 覆盖 CTE 字段
sa12 = mime.parse_message(raw12.decode(), None, None)
sb12 = mime.parse_message(raw12c.decode(), "multipart/mixed", "E")
d12 = diff.diff_results({"tree": sa12["tree"], "issues": sa12["issues"]},
                        {"tree": sb12["tree"], "issues": sb12["issues"]})
by_path12 = {e["path"]: e for e in d12["entries"]}
p0_fields = {f["field"] for f in by_path12["parts[0]"]["fields"]}
check("diff 检出传输编码差异", "cte" in p0_fields, p0_fields)

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)