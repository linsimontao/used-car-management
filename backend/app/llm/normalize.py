"""車両番号の正規化（SPEC §7.5）。

音声経路において最も誤りが生じやすい箇所であり、
LLM の出力に対してバックエンドで決定的な後処理を必ず行う。

適用順序：
  1. 全角 → 半角
  2. 漢数字 → アラビア数字
  3. 数字の読み（ひらがな・カタカナ）→ 数字
  4. 位取りの読み（ひゃく／せん）の解決
  5. 接尾辞・指示語の除去（番、番の車、号車、の車 など）
  6. 残った非数字文字と空白の除去
  7. 3〜4桁の数字であることの検証。満たさなければ None

手順 6 は「意味を持たない残りかす」だけを落とす。読みに使われうるかな文字が
残っている場合は番号表現ではないと判断して None を返す —— 「番号わかりません」の
「ません」を「せん＝1000の位」と解釈して 1000 番の車を掴んでしまうような
取り違えは、誤ったロックに直結するため決して起こしてはならない。

実装上の注意：手順 3 を素朴に先に適用すると「ひゃく」の「く」が 9 に化けて
「ひゃくいち」が 101 ではなく「ひゃ91」になる。そのため位取りの読みを先に
内部マーカー（S/H/T）へ退避させてから数字の読みを変換する。
"""

import re
import unicodedata

# 漢数字 → アラビア数字（SPEC §7.5-2）
KANJI_DIGITS: dict[str, str] = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}

# 数字の読み → アラビア数字（SPEC §7.5-3）
KANA_DIGITS: dict[str, str] = {
    "まる": "0", "マル": "0", "ぜろ": "0", "ゼロ": "0", "れい": "0", "レイ": "0",
    "いち": "1", "イチ": "1",
    "に": "2", "ニ": "2",
    "さん": "3", "サン": "3",
    "よん": "4", "し": "4", "ヨン": "4", "シ": "4",
    "ご": "5", "ゴ": "5",
    "ろく": "6", "ろっ": "6", "ロク": "6", "ロッ": "6",
    "なな": "7", "しち": "7", "ナナ": "7", "シチ": "7",
    "はち": "8", "はっ": "8", "ハチ": "8", "ハッ": "8",
    "きゅう": "9", "きゅー": "9", "く": "9", "キュウ": "9", "キュー": "9", "ク": "9",
}

# 位取りの読み → 内部マーカー（SPEC §7.5-4）。連濁（びゃく／ぜん）も受け付ける
UNIT_READINGS: dict[str, str] = {
    "せん": "S", "ぜん": "S", "千": "S", "セン": "S", "ゼン": "S",
    "ひゃく": "H", "びゃく": "H", "ぴゃく": "H", "百": "H",
    "ヒャク": "H", "ビャク": "H", "ピャク": "H",
    "じゅう": "T", "じゅっ": "T", "じゅー": "T", "十": "T",
    "ジュウ": "T", "ジュッ": "T", "ジュー": "T",
}

# 内部マーカーの重み
UNIT_VALUES: dict[str, int] = {"S": 1000, "H": 100, "T": 10}

# 数字にも位取りにも寄与しない「残りかす」。除去しても意味を変えない表現に限る
NOISE_WORDS: tuple[str, ...] = (
    "ばんめ", "ばん", "ごうしゃ", "くるま", "ですね", "です", "だよ", "って", "ね",
    "番の車", "号車", "番車", "の車", "番", "車", "の",
)

# 記号・ラテン文字も番号の意味に寄与しないため除去してよい（No.101 / #101 など）
# 促音（っ／ッ）は「はっぴゃく」「じゅっ」の読みに寄与するため除去しない
NOISE_CHARS = re.compile(r"[A-Za-z.#:：/№()（）\-ー―、。,]")

# 数字・位取りへの変換を終えた後になお残る漢字（SPEC §7.5-6）。
# 変換後の漢字は数値に寄与しないため落としてよい。Gemini が「101番」の「番」を
# 字形の近い「畦」として出力する事象を実測しており、こうした揺れを吸収する。
# かな文字は「ません」の「せん」のような取り違えを弾く手掛かりとして残す。
RESIDUAL_KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

# 除去する接尾辞・指示語（SPEC §7.5-5）。長いものから順に適用すること
SUFFIXES: tuple[str, ...] = (
    "番の車", "号車", "番車", "の車", "あの車", "この車", "番", "さん",
)


def normalize_vehicle_no(raw: str | None) -> str | None:
    """発話由来の管理番号表現を 3〜4桁の数字文字列に正規化する。

    変換例：「イチマルイチ番の車」→ "101"／「一〇一番」→ "101"／
            「二〇三五」→ "2035"／「ひゃくいちばん」→ "101"
    正規化できない場合は None を返す（呼び出し元が missing に積む）。
    """
    if raw is None:
        return None

    # 1. 全角 → 半角。空白も落とす（「1 0 1」のような区切りを吸収する）
    text = unicodedata.normalize("NFKC", raw)
    text = re.sub(r"\s+", "", text)
    if not text:
        return None

    # 2. 漢数字 → アラビア数字
    text = text.translate(str.maketrans(KANJI_DIGITS))

    # 5. 接尾辞・指示語の除去（数字の読みへの変換前に行う。「さん」の扱いを参照）
    text = _strip_suffixes(text)

    # 6. 意味を持たない残りかす（記号・助数詞など）の除去。
    #    位取りマーカーを導入する前に行う —— マーカーは英字であり、
    #    記号除去を後に回すとマーカー自身が消えてしまう
    text = _strip_noise(text)

    # 4'. 位取りの読みを内部マーカーへ退避（3 の前に行う。モジュール冒頭の注意を参照）
    text = _replace_all(text, UNIT_READINGS)

    # 3. 数字の読み → アラビア数字
    text = _replace_all(text, KANA_DIGITS)

    # 変換後に残った漢字を落とす（位取りの漢字は既にマーカー化されている）
    text = RESIDUAL_KANJI.sub("", text)

    # 数字と位取りマーカー以外が残っていないことを確かめる。位取りの解決より前に
    #    検査する —— 「ません」の「せん」を 1000 と解決してから検査したのでは、
    #    番号でない文字列が番号として通ってしまう
    if re.search(r"[^0-9SHT]", text):
        return None

    # 4. 位取りマーカーを含む場合のみ算術で解決する
    if any(marker in text for marker in UNIT_VALUES):
        value = _resolve_units(text)
        text = "" if value is None else str(value)

    # 7. 3〜4桁であることの検証
    return text if re.fullmatch(r"\d{3,4}", text) else None


def _strip_noise(text: str) -> str:
    """意味を持たない残りかす（「ばん」「です」「-」など）を取り除く。"""
    for word in sorted(NOISE_WORDS, key=len, reverse=True):
        text = text.replace(word, "")
    return NOISE_CHARS.sub("", text)


def _strip_suffixes(text: str) -> str:
    """末尾の接尾辞・指示語を、無くなるまで長いものから順に取り除く。

    「さん」は敬称（101さん）と数字の読み（いちまるさん = 103）の両義であるため、
    直前がアラビア数字のときだけ敬称と見なして除去する。
    """
    ordered = sorted(SUFFIXES, key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        for suffix in ordered:
            if not text.endswith(suffix):
                continue
            if suffix == "さん":
                head = text[: -len(suffix)]
                if not (head and head[-1].isdigit()):
                    continue
            text = text[: -len(suffix)]
            changed = True
            break
    return text


def _replace_all(text: str, table: dict[str, str]) -> str:
    """読みの表を長いキーから順に適用する（「しち」が「し」に食われないように）。"""
    for reading in sorted(table, key=len, reverse=True):
        text = text.replace(reading, table[reading])
    return text


def _resolve_units(text: str) -> int | None:
    """「2S3T5」のような数字＋位取りマーカー列を 2035 に解決する。

    マーカーの直前に数字が無い場合は 1 と見なす（「ひゃくいち」→ 100 + 1）。
    マーカーを 1 つも消化できなかった場合は None を返す。
    """
    total = 0
    current = 0
    consumed = False
    for char in text:
        if char.isdigit():
            current = current * 10 + int(char)
        elif char in UNIT_VALUES:
            total += (current or 1) * UNIT_VALUES[char]
            current = 0
            consumed = True
        # それ以外（除去されずに残った助詞など）は無視する
    return total + current if consumed else None
