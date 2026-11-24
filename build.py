import datetime
import hashlib
import io
import os
import struct
import sys
import zlib

URL = "https://alphaxiv-scroll.vercel.app/"
PKG = "app.alphaxiv.scroll"
LABEL = "alphaXiv Scroll"
VERSION_CODE, VERSION_NAME = 2, "1.1"
MIN_SDK, TARGET_SDK = 24, 34
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "alphaxiv-scroll.apk")
LOGO = os.path.join(HERE, "assets", "logo.png")
KEY_DIR = os.path.join(HERE, "keystore")

ANDROID_NS = "http://schemas.android.com/apk/res/android"
T_REF, T_STR, T_DEC, T_HEX, T_BOOL = 0x01, 0x03, 0x10, 0x11, 0x12

MIPMAP_ICON, MIPMAP_FG = 0x7F010000, 0x7F010001
DENSITIES = [("mdpi", 160, 48), ("hdpi", 240, 72), ("xhdpi", 320, 96), ("xxhdpi", 480, 144), ("xxxhdpi", 640, 192)]

ATTRS = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "icon": 0x01010002,
    "name": 0x01010003,
    "exported": 0x01010010,
    "launchMode": 0x0101001D,
    "configChanges": 0x0101001F,
    "drawable": 0x01010199,
    "minSdkVersion": 0x0101020C,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "targetSdkVersion": 0x01010270,
    "allowBackup": 0x01010280,
    "hardwareAccelerated": 0x010102D3,
}
THEME_MATERIAL_NO_ACTION_BAR = 0x0103022E
COLOR_BLACK = 0x0106000C


def string_pool(strings):
    offsets, data = [], b""
    for s in strings:
        offsets.append(len(data))
        u = s.encode("utf-16-le")
        data += struct.pack("<H", len(u) // 2) + u + b"\0\0"
    data += b"\0" * (-len(data) % 4)
    start = 28 + 4 * len(strings)
    return (struct.pack("<HHIIIIII", 0x0001, 28, start + len(data), len(strings), 0, 0, start, 0)
            + b"".join(struct.pack("<I", o) for o in offsets) + data)


def axml(root, root_plain_attrs=()):
    names = [n for n in ATTRS if any_attr(root, n)]
    strings = names[:]

    def s(value):
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    ns_prefix, ns_uri = s("android"), s(ANDROID_NS)
    body = []

    def attr(name_idx, ns, kind, value):
        if kind == T_STR:
            vi = s(value)
            return struct.pack("<iiiHBBI", ns, name_idx, vi, 8, 0, T_STR, vi)
        if kind == T_BOOL:
            value = 0xFFFFFFFF if value else 0
        return struct.pack("<iiiHBBI", ns, name_idx, -1, 8, 0, kind, value & 0xFFFFFFFF)

    def walk(node, plain=()):
        tag, attrs, children = node
        tag_idx = s(tag)
        encoded = [attr(names.index(n), ns_uri, k, v) for n, k, v in sorted(attrs, key=lambda a: ATTRS[a[0]])]
        encoded += [attr(s(n), -1, T_STR, v) for n, v in plain]
        ext = struct.pack("<iiHHHHHH", -1, tag_idx, 0x14, 0x14, len(encoded), 0, 0, 0) + b"".join(encoded)
        body.append(struct.pack("<HHIii", 0x0102, 16, 16 + len(ext), 1, -1) + ext)
        for child in children:
            walk(child)
        body.append(struct.pack("<HHIiiii", 0x0103, 16, 24, 1, -1, -1, tag_idx))

    walk(root, root_plain_attrs)
    ns_start = struct.pack("<HHIiiii", 0x0100, 16, 24, 1, -1, ns_prefix, ns_uri)
    ns_end = struct.pack("<HHIiiii", 0x0101, 16, 24, 1, -1, ns_prefix, ns_uri)
    res_map = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(names)) + b"".join(struct.pack("<I", ATTRS[n]) for n in names)
    payload = string_pool(strings) + res_map + ns_start + b"".join(body) + ns_end
    return struct.pack("<HHI", 0x0003, 8, 8 + len(payload)) + payload


def any_attr(node, name):
    tag, attrs, children = node
    return any(a[0] == name for a in attrs) or any(any_attr(c, name) for c in children)


def res_config(density=0, sdk=0):
    c = struct.pack("<I", 64) + b"\0" * 8
    c += struct.pack("<BBH", 0, 0, density)
    c += b"\0" * 8
    c += struct.pack("<HH", sdk, 0)
    return c + b"\0" * (64 - len(c))


def res_type_chunk(type_id, config, entries):
    header = 20 + len(config)
    offsets, data = [], b""
    for entry in entries:
        if entry is None:
            offsets.append(0xFFFFFFFF)
            continue
        offsets.append(len(data))
        data += struct.pack("<HHI", 8, 0, entry[0]) + struct.pack("<HBBI", 8, 0, T_STR, entry[1])
    start = header + 4 * len(entries)
    return (struct.pack("<HHIBBHII", 0x0201, header, start + len(data), type_id, 0, 0, len(entries), start)
            + config + b"".join(struct.pack("<I", o) for o in offsets) + data)


def resources_arsc(files):
    index = files.index
    keys = ["ic_launcher", "ic_launcher_foreground"]
    chunks = struct.pack("<HHIBBHI", 0x0202, 16, 24, 1, 0, 0, 2) + struct.pack("<II", 0x0500, 0x0100)
    for name, dpi, _ in DENSITIES:
        chunks += res_type_chunk(1, res_config(dpi, 4), [
            (0, index(f"res/mipmap-{name}-v4/ic_launcher.png")),
            (1, index(f"res/mipmap-{name}-v4/ic_launcher_foreground.png")),
        ])
    chunks += res_type_chunk(1, res_config(0xFFFE, 26), [(0, index("res/mipmap-anydpi-v26/ic_launcher.xml")), None])
    type_pool, key_pool = string_pool(["mipmap"]), string_pool(keys)
    header = 288
    body = type_pool + key_pool + chunks
    package = (struct.pack("<HHII", 0x0200, header, header + len(body), 0x7F)
               + PKG.encode("utf-16-le").ljust(256, b"\0")
               + struct.pack("<IIIII", header, 1, header + len(type_pool), len(keys), 0) + body)
    pool = string_pool(files)
    return struct.pack("<HHII", 0x0002, 12, 12 + len(pool) + len(package), 1) + pool + package


def uleb(v):
    out = b""
    while True:
        b, v = v & 0x7F, v >> 7
        if not v:
            return out + bytes([b])
        out += bytes([b | 0x80])


ACT = "Landroid/app/Activity;"
WV = "Landroid/webkit/WebView;"
WS = "Landroid/webkit/WebSettings;"
WVC = "Landroid/webkit/WebViewClient;"
WCC = "Landroid/webkit/WebChromeClient;"
MAIN = "L" + PKG.replace(".", "/") + "/MainActivity;"
FIELD_WEB = (MAIN, WV, "web")


def m(cls, name, ret, *params):
    return cls, name, ret, tuple(params)


def code_init():
    return 1, 1, [("invoke-direct", [0], m(ACT, "<init>", "V")), ("return-void",)]


def code_on_create():
    return 5, 2, [
        ("invoke-super", [3, 4], m(ACT, "onCreate", "V", "Landroid/os/Bundle;")),
        ("new-instance", 0, WV),
        ("invoke-direct", [0, 3], m(WV, "<init>", "V", "Landroid/content/Context;")),
        ("iput-object", 0, 3, FIELD_WEB),
        ("const/high16", 1, 0xFF00),
        ("invoke-virtual", [0, 1], m(WV, "setBackgroundColor", "V", "I")),
        ("invoke-virtual", [0], m(WV, "getSettings", WS)),
        ("move-result-object", 1),
        ("const/4", 2, 1),
        ("invoke-virtual", [1, 2], m(WS, "setJavaScriptEnabled", "V", "Z")),
        ("invoke-virtual", [1, 2], m(WS, "setDomStorageEnabled", "V", "Z")),
        ("const/4", 2, 0),
        ("invoke-virtual", [1, 2], m(WS, "setMediaPlaybackRequiresUserGesture", "V", "Z")),
        ("new-instance", 1, WVC),
        ("invoke-direct", [1], m(WVC, "<init>", "V")),
        ("invoke-virtual", [0, 1], m(WV, "setWebViewClient", "V", WVC)),
        ("new-instance", 1, WCC),
        ("invoke-direct", [1], m(WCC, "<init>", "V")),
        ("invoke-virtual", [0, 1], m(WV, "setWebChromeClient", "V", WCC)),
        ("const-string", 1, URL),
        ("invoke-virtual", [0, 1], m(WV, "loadUrl", "V", "Ljava/lang/String;")),
        ("invoke-virtual", [3, 0], m(ACT, "setContentView", "V", "Landroid/view/View;")),
        ("return-void",),
    ]


def code_on_back():
    return 3, 1, [
        ("iget-object", 0, 2, FIELD_WEB),
        ("if-eqz", 0, 12),
        ("invoke-virtual", [0], m(WV, "canGoBack", "Z")),
        ("move-result", 1),
        ("if-eqz", 1, 6),
        ("invoke-virtual", [0], m(WV, "goBack", "V")),
        ("return-void",),
        ("invoke-super", [2], m(ACT, "onBackPressed", "V")),
        ("return-void",),
    ]


def code_lifecycle(name, webview_method):
    return 2, 1, [
        ("invoke-super", [1], m(ACT, name, "V")),
        ("iget-object", 0, 1, FIELD_WEB),
        ("if-eqz", 0, 5),
        ("invoke-virtual", [0], m(WV, webview_method, "V")),
        ("return-void",),
    ]


METHODS = [
    ("<init>", "V", (), 0x10001, True, code_init()),
    ("onCreate", "V", ("Landroid/os/Bundle;",), 0x4, False, code_on_create()),
    ("onBackPressed", "V", (), 0x1, False, code_on_back()),
    ("onPause", "V", (), 0x1, False, code_lifecycle("onPause", "onPause")),
    ("onResume", "V", (), 0x1, False, code_lifecycle("onResume", "onResume")),
    ("onDestroy", "V", (), 0x1, False, code_lifecycle("onDestroy", "destroy")),
]

OPCODES = {"invoke-virtual": 0x6E, "invoke-super": 0x6F, "invoke-direct": 0x70}


def shorty_char(t):
    return "L" if t[0] == "[" else t[0]


def shorty(ret, params):
    return shorty_char(ret) + "".join(shorty_char(p) for p in params)


def build_dex():
    strings, types, protos, fields, methods = set(), set(), set(), set(), set()

    def add_type(t):
        types.add(t)
        strings.add(t)

    def add_method(meth):
        cls, name, ret, params = meth
        add_type(cls)
        strings.add(name)
        add_type(ret)
        for p in params:
            add_type(p)
        strings.add(shorty(ret, params))
        protos.add((ret, params))
        methods.add(meth)

    add_type(MAIN)
    add_type(ACT)
    add_type(WV)
    fields.add(FIELD_WEB)
    strings.add("web")
    for name, ret, params, *_ in METHODS:
        add_method((MAIN, name, ret, params))
    for *_, (_, _, code) in METHODS:
        for ins in code:
            for a in ins[1:]:
                if isinstance(a, tuple) and len(a) == 4:
                    add_method(a)
                elif isinstance(a, str) and a.startswith("L") and a.endswith(";"):
                    add_type(a)
                elif isinstance(a, str):
                    strings.add(a)

    strings = sorted(strings, key=lambda x: [ord(c) for c in x])
    si = {x: i for i, x in enumerate(strings)}
    types = sorted(types, key=lambda t: si[t])
    ti = {t: i for i, t in enumerate(types)}
    protos = sorted(protos, key=lambda p: (ti[p[0]], [ti[x] for x in p[1]]))
    pi = {p: i for i, p in enumerate(protos)}
    fields = sorted(fields, key=lambda f: (ti[f[0]], si[f[2]], ti[f[1]]))
    fi = {f: i for i, f in enumerate(fields)}
    methods = sorted(methods, key=lambda x: (ti[x[0]], si[x[1]], pi[(x[2], x[3])]))
    mi = {x: i for i, x in enumerate(methods)}

    def encode(ins):
        op = ins[0]
        if op == "return-void":
            return [0x000E]
        if op in OPCODES:
            regs, meth = ins[1], ins[2]
            r = regs + [0] * (5 - len(regs))
            return [(len(regs) << 12) | (r[4] << 8) | OPCODES[op], mi[meth],
                    (r[3] << 12) | (r[2] << 8) | (r[1] << 4) | r[0]]
        if op == "new-instance":
            return [(ins[1] << 8) | 0x22, ti[ins[2]]]
        if op == "const-string":
            return [(ins[1] << 8) | 0x1A, si[ins[2]]]
        if op == "iput-object":
            return [(ins[2] << 12) | (ins[1] << 8) | 0x5B, fi[ins[3]]]
        if op == "iget-object":
            return [(ins[2] << 12) | (ins[1] << 8) | 0x54, fi[ins[3]]]
        if op == "move-result-object":
            return [(ins[1] << 8) | 0x0C]
        if op == "move-result":
            return [(ins[1] << 8) | 0x0A]
        if op == "const/4":
            return [((ins[2] & 0xF) << 12) | (ins[1] << 8) | 0x12]
        if op == "const/high16":
            return [(ins[1] << 8) | 0x15, ins[2]]
        if op == "if-eqz":
            return [(ins[1] << 8) | 0x38, ins[2] & 0xFFFF]
        raise ValueError(op)

    def outs(code):
        return max([len(i[1]) for i in code if i[0] in OPCODES] + [0])

    off = 0x70
    str_ids_off = off
    off += 4 * len(strings)
    type_ids_off = off
    off += 4 * len(types)
    proto_ids_off = off
    off += 12 * len(protos)
    field_ids_off = off
    off += 8 * len(fields)
    method_ids_off = off
    off += 8 * len(methods)
    class_defs_off = off
    off += 32
    data_off = off
    data = bytearray()

    def pos():
        return data_off + len(data)

    def align():
        while pos() % 4:
            data.append(0)

    type_list_off = {}
    for p in protos:
        if p[1] and p[1] not in type_list_off:
            align()
            type_list_off[p[1]] = pos()
            data.extend(struct.pack("<I", len(p[1])) + b"".join(struct.pack("<H", ti[t]) for t in p[1]))

    align()
    code_start, code_off = pos(), {}
    for name, ret, params, _, _, (regs, ins_size, code) in METHODS:
        align()
        code_off[(MAIN, name, ret, params)] = pos()
        insns = [w for i in code for w in encode(i)]
        data.extend(struct.pack("<HHHHII", regs, ins_size, outs(code), 0, 0, len(insns)))
        data.extend(b"".join(struct.pack("<H", w) for w in insns))

    string_data_start, string_data_off = pos(), []
    for x in strings:
        string_data_off.append(pos())
        data.extend(uleb(len(x)) + x.encode("utf-8") + b"\0")

    class_data_off = pos()
    key = lambda meth: mi[(MAIN, meth[0], meth[1], meth[2])]
    direct = sorted([x for x in METHODS if x[4]], key=key)
    virtual = sorted([x for x in METHODS if not x[4]], key=key)
    cd = uleb(0) + uleb(1) + uleb(len(direct)) + uleb(len(virtual)) + uleb(fi[FIELD_WEB]) + uleb(0x2)
    for group in (direct, virtual):
        prev = 0
        for name, ret, params, access, _, _ in group:
            k = (MAIN, name, ret, params)
            cd += uleb(mi[k] - prev) + uleb(access) + uleb(code_off[k])
            prev = mi[k]
    data.extend(cd)

    align()
    map_off = pos()
    items = [(0x0000, 1, 0), (0x0001, len(strings), str_ids_off), (0x0002, len(types), type_ids_off),
             (0x0003, len(protos), proto_ids_off), (0x0004, len(fields), field_ids_off),
             (0x0005, len(methods), method_ids_off), (0x0006, 1, class_defs_off)]
    if type_list_off:
        items.append((0x1001, len(type_list_off), min(type_list_off.values())))
    items += [(0x2001, len(METHODS), code_start), (0x2002, len(strings), string_data_start),
              (0x2000, 1, class_data_off), (0x1000, 1, map_off)]
    data.extend(struct.pack("<I", len(items)) + b"".join(struct.pack("<HHII", t, 0, n, o) for t, n, o in items))
    file_size = data_off + len(data)

    ids = bytearray()
    ids += b"".join(struct.pack("<I", o) for o in string_data_off)
    ids += b"".join(struct.pack("<I", si[t]) for t in types)
    for p in protos:
        ids += struct.pack("<III", si[shorty(*p)], ti[p[0]], type_list_off.get(p[1], 0))
    for f in fields:
        ids += struct.pack("<HHI", ti[f[0]], ti[f[1]], si[f[2]])
    for x in methods:
        ids += struct.pack("<HHI", ti[x[0]], pi[(x[2], x[3])], si[x[1]])
    ids += struct.pack("<IIIIIIII", ti[MAIN], 0x1, ti[ACT], 0, 0xFFFFFFFF, 0, class_data_off, 0)

    header = bytearray(b"dex\n035\0" + b"\0" * 24)
    header += struct.pack("<IIIIII", file_size, 0x70, 0x12345678, 0, 0, map_off)
    header += struct.pack("<IIIIIIIIIIIIII", len(strings), str_ids_off, len(types), type_ids_off,
                          len(protos), proto_ids_off, len(fields), field_ids_off, len(methods), method_ids_off,
                          1, class_defs_off, len(data), data_off)
    dex = bytearray(header + ids + data)
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    dex[8:12] = struct.pack("<I", zlib.adler32(bytes(dex[12:])))
    return bytes(dex)


def make_icons():
    from PIL import Image, ImageDraw

    src = Image.open(LOGO).convert("RGBA")
    size = max(src.size)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    square.paste(src, ((size - src.size[0]) // 2, (size - src.size[1]) // 2))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([size * 0.025, size * 0.025, size * 0.975, size * 0.975],
                                           radius=size * 0.2, fill=255)
    legacy = square.copy()
    legacy.putalpha(mask)

    out = {}
    for name, _, px in DENSITIES:
        buf = io.BytesIO()
        legacy.resize((px, px), Image.LANCZOS).save(buf, "PNG", optimize=True)
        out[f"res/mipmap-{name}-v4/ic_launcher.png"] = buf.getvalue()

        canvas = px * 108 // 48
        inner = int(canvas * 0.74)
        fg = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 255))
        fg.alpha_composite(square.resize((inner, inner), Image.LANCZOS), ((canvas - inner) // 2,) * 2)
        buf = io.BytesIO()
        fg.save(buf, "PNG", optimize=True)
        out[f"res/mipmap-{name}-v4/ic_launcher_foreground.png"] = buf.getvalue()
    return out


def build_zip(entries):
    out, cd = bytearray(), bytearray()
    dos_date = (2026 - 1980) << 9 | 1 << 5 | 1
    for name, data, compress in entries:
        nb = name.encode()
        crc = zlib.crc32(data) & 0xFFFFFFFF
        if compress:
            co = zlib.compressobj(9, zlib.DEFLATED, -15)
            body, method = co.compress(data) + co.flush(), 8
        else:
            body, method = data, 0
        offset = len(out)
        extra = b"\0" * ((-(offset + 30 + len(nb))) % 4) if method == 0 else b""
        out += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0800, method, 0, dos_date, crc,
                           len(body), len(data), len(nb), len(extra)) + nb + extra + body
        cd += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0800, method, 0, dos_date, crc,
                          len(body), len(data), len(nb), 0, 0, 0, 0, 0, offset) + nb
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(cd), len(out), 0)
    return bytes(out), bytes(cd), eocd


def lp(b):
    return struct.pack("<I", len(b)) + b


def sign_v2(entries_blob, cd, eocd, key, cert_der):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def chunks(b):
        return [b[i:i + 1048576] for i in range(0, len(b), 1048576)]

    eocd_digest = bytearray(eocd)
    eocd_digest[16:20] = struct.pack("<I", len(entries_blob))
    parts = chunks(entries_blob) + chunks(cd) + chunks(bytes(eocd_digest))
    digests = [hashlib.sha256(b"\xa5" + struct.pack("<I", len(c)) + c).digest() for c in parts]
    top = hashlib.sha256(b"\x5a" + struct.pack("<I", len(digests)) + b"".join(digests)).digest()

    alg = 0x0103
    signed_data = lp(lp(struct.pack("<I", alg) + lp(top))) + lp(lp(cert_der)) + lp(b"")
    signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    public_key = key.public_key().public_bytes(serialization.Encoding.DER,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    signer = lp(signed_data) + lp(lp(struct.pack("<I", alg) + lp(signature))) + lp(public_key)
    value = lp(lp(signer))
    pair = struct.pack("<QI", 4 + len(value), 0x7109871A) + value
    size = len(pair) + 24
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + b"APK Sig Block 42"

    final_eocd = bytearray(eocd)
    final_eocd[16:20] = struct.pack("<I", len(entries_blob) + len(block))
    return entries_blob + block + cd + bytes(final_eocd)


def load_or_create_key():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key_path = os.path.join(KEY_DIR, "signing-key.pem")
    cert_path = os.path.join(KEY_DIR, "signing-cert.der")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), None)
        with open(cert_path, "rb") as f:
            return key, f.read()

    os.makedirs(KEY_DIR, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, LABEL)])
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(start)
            .not_valid_after(start + datetime.timedelta(days=365 * 30)).sign(key, hashes.SHA256()))
    der = cert.public_bytes(serialization.Encoding.DER)
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(der)
    return key, der


def manifest():
    tree = ("manifest", [("versionCode", T_DEC, VERSION_CODE), ("versionName", T_STR, VERSION_NAME)], [
        ("uses-sdk", [("minSdkVersion", T_DEC, MIN_SDK), ("targetSdkVersion", T_DEC, TARGET_SDK)], []),
        ("uses-permission", [("name", T_STR, "android.permission.INTERNET")], []),
        ("uses-permission", [("name", T_STR, "android.permission.ACCESS_NETWORK_STATE")], []),
        ("application", [
            ("label", T_STR, LABEL),
            ("icon", T_REF, MIPMAP_ICON),
            ("allowBackup", T_BOOL, True),
            ("hardwareAccelerated", T_BOOL, True),
            ("theme", T_REF, THEME_MATERIAL_NO_ACTION_BAR),
        ], [
            ("activity", [
                ("name", T_STR, PKG + ".MainActivity"),
                ("exported", T_BOOL, True),
                ("launchMode", T_DEC, 1),
                ("configChanges", T_HEX, 0x0FB0),
            ], [
                ("intent-filter", [], [
                    ("action", [("name", T_STR, "android.intent.action.MAIN")], []),
                    ("category", [("name", T_STR, "android.intent.category.LAUNCHER")], []),
                ]),
            ]),
        ]),
    ])
    return axml(tree, [("package", PKG)])


def adaptive_icon():
    return axml(("adaptive-icon", [], [
        ("background", [("drawable", T_REF, COLOR_BLACK)], []),
        ("foreground", [("drawable", T_REF, MIPMAP_FG)], []),
    ]))


def main():
    icons = make_icons()
    adaptive_path = "res/mipmap-anydpi-v26/ic_launcher.xml"
    entries = [
        ("AndroidManifest.xml", manifest(), True),
        ("classes.dex", build_dex(), True),
        ("resources.arsc", resources_arsc(sorted(icons) + [adaptive_path]), False),
        (adaptive_path, adaptive_icon(), True),
    ] + [(n, icons[n], False) for n in sorted(icons)]
    blob, cd, eocd = build_zip(entries)
    key, cert = load_or_create_key()
    apk = sign_v2(blob, cd, eocd, key, cert)
    with open(OUT, "wb") as f:
        f.write(apk)
    print(f"{OUT} ({len(apk)} bytes)")


if __name__ == "__main__":
    main()
