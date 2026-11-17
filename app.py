"""한입공유 — Streamlit 공유 레시피 앱
실행: pip install -r requirements.txt && streamlit run app.py

제작자 최초 설정 (가족 이용자는 설정하지 않습니다)
1. GitHub 저장소에 app.py, requirements.txt 업로드 후 Streamlit Community Cloud 배포.
2. Supabase 등에서 PostgreSQL 프로젝트 생성 후 Connect에서 Session pooler 연결 문자열 복사.
   Streamlit Cloud에서는 IPv4를 지원하는 Session pooler 연결을 권장합니다.
3. Streamlit 앱 Settings > Secrets에 아래 한 줄을 실제 값으로 저장:
   DATABASE_URL = "postgresql://사용자:암호@호스트:5432/postgres?sslmode=require"
   비밀번호 특수문자는 URL 인코딩. 비밀값은 GitHub/채팅에 올리지 않습니다.
4. 테이블은 앱이 자동 생성합니다. 연결 후 두 휴대폰에서 가입/로그인해 공유를 확인하세요.

설정 전: 예시 레시피 탐색만 가능합니다. 가짜 업로드 성공 처리는 하지 않습니다.
설정 후: 회원, 레시피 사진, 찜은 PostgreSQL에 영구 저장됩니다.
공개 인터넷용 대규모 서비스가 아닌 소규모 가족 시제품입니다.
암호는 salt+PBKDF2로 저장. 로그인은 현재 접속 세션 동안 유지됩니다.
DB 사용자는 이 앱 전용으로 생성하고 다른 민감한 데이터와 분리하세요.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import html
import io
import json
import os
import secrets
import unicodedata
import uuid
from datetime import datetime, timezone

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

CATEGORIES = {"전체": "🍽️", "밥·죽": "🍚", "면": "🍜", "국·찌개": "🥘", "반찬": "🥗", "고기": "🍖", "간식": "🍪"}
SAMPLES = [
    dict(id="sample-1", title="한 그릇 간장계란밥", author="한입공유", category="밥·죽", minutes=10, servings=1,
         ingredients="밥 1공기\n달걀 1개\n간장 1작은술\n참기름 1작은술\n김가루 약간",
         steps=["달걀을 프라이팬에서 흰자와 노른자가 충분히 익도록 익혀요.", "밥 위에 달걀을 올리고 간장과 참기름을 넣어요.", "김가루를 뿌린 뒤 골고루 비벼요. 간장은 입맛에 맞게 조금씩 더해요."],
         tip="간장은 처음부터 많이 넣지 않고 맛을 보며 더해요.", photo=None, sample=True),
    dict(id="sample-2", title="보글보글 두부 된장찌개", author="한입공유", category="국·찌개", minutes=20, servings=2,
         ingredients="두부 150g\n애호박 1/3개\n양파 1/4개\n물 500mL\n된장 1큰술\n다진 마늘 1작은술",
         steps=["두부와 채소를 한입 크기로 썰어요.", "냄비에 물과 된장을 풀고 양파와 애호박을 넣어 끓여요.", "채소가 익으면 두부와 다진 마늘을 넣고 3~5분 더 끓여요."],
         tip="된장마다 짠맛이 달라요. 부족한 간은 마지막에 맞춰요.", photo=None, sample=True),
    dict(id="sample-3", title="바삭한 식빵 치즈토스트", author="한입공유", category="간식", minutes=10, servings=1,
         ingredients="식빵 2장\n슬라이스 치즈 1장\n버터 5g",
         steps=["식빵 사이에 치즈를 넣어요.", "약불로 달군 팬에 버터를 녹이고 식빵을 올려요.", "앞뒤로 뒤집어 겉은 노릇하게, 속의 치즈는 녹도록 구워요."],
         tip="불이 세면 빵만 타요. 약불에서 천천히 구워요.", photo=None, sample=True),
]


def esc(value):
    return html.escape(str(value), quote=True)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()


def prepare_photo(raw):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("사진은 8MB 이하로 올려 주세요.")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.width * original.height > 24_000_000:
                raise ValueError("사진 크기가 너무 커요. 작은 사진을 골라 주세요.")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1200, 1200))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=82)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("읽을 수 없는 사진이에요. JPG 또는 PNG로 다시 골라 주세요.") from exc


def make_sample_photo(category):
    # 예시임을 명시하는 자체 제작 그림. 실제 게시물은 올린 음식 사진을 사용합니다.
    from PIL import ImageDraw
    image = Image.new("RGB", (800, 420), "#EAF7F4")
    d = ImageDraw.Draw(image)
    d.ellipse((215, 40, 585, 395), fill="#CFDFDA")
    d.ellipse((205, 25, 575, 380), fill="#FFFFFF")
    if category == "밥·죽":
        d.ellipse((265, 80, 520, 325), fill="#FFF0C9")
        d.ellipse((300, 105, 500, 290), fill="#FFFFFF")
        d.ellipse((360, 150, 455, 240), fill="#FFBD39")
        for x, y in [(305, 200), (460, 120), (430, 285), (280, 250)]:
            d.rounded_rectangle((x, y, x+30, y+10), 4, fill="#386955")
    elif category == "국·찌개":
        d.ellipse((250, 70, 530, 335), fill="#AC713F")
        for x, y in [(300, 110), (420, 170), (335, 235)]:
            d.rounded_rectangle((x, y, x+65, y+50), 7, fill="#FFF3CF")
        for x, y in [(285, 210), (420, 100), (415, 270)]:
            d.ellipse((x, y, x+40, y+25), fill="#6B9965")
    else:
        d.rounded_rectangle((275, 95, 510, 305), 28, fill="#BC7942")
        d.rounded_rectangle((295, 110, 490, 285), 22, fill="#F7C674")
        d.polygon([(300, 120), (480, 270), (320, 260)], fill="#FFE59C")
    output = io.BytesIO()
    image.save(output, "JPEG", quality=85)
    return output.getvalue()


@st.cache_resource
def sample_photo(category):
    return make_sample_photo(category)


def db_connect(url):
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(url, connect_timeout=8, row_factory=dict_row)


@st.cache_resource
def initialize_db(url):
    with db_connect(url) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS hanip_users (
            id TEXT PRIMARY KEY, handle TEXT UNIQUE NOT NULL, nickname TEXT NOT NULL,
            salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hanip_recipes (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES hanip_users(id),
            title TEXT NOT NULL, category TEXT NOT NULL, minutes INTEGER NOT NULL,
            servings INTEGER NOT NULL, ingredients TEXT NOT NULL, steps TEXT NOT NULL,
            tip TEXT NOT NULL, photo BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hanip_favorites (
            user_id TEXT REFERENCES hanip_users(id) ON DELETE CASCADE,
            recipe_id TEXT REFERENCES hanip_recipes(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, recipe_id))""")
    return True


def get_recipes(url):
    with db_connect(url) as conn:
        rows = conn.execute("""SELECT r.*, u.nickname AS author FROM hanip_recipes r
            JOIN hanip_users u ON r.user_id=u.id ORDER BY r.created_at DESC LIMIT 200""").fetchall()
    for row in rows:
        row["steps"] = json.loads(row["steps"])
        row["photo"] = bytes(row["photo"])
        row["sample"] = False
    return rows


def get_favorites(url, uid):
    if not uid:
        return set()
    with db_connect(url) as conn:
        return {r["recipe_id"] for r in conn.execute(
            "SELECT recipe_id FROM hanip_favorites WHERE user_id=%s", (uid,)).fetchall()}


def photo_for(recipe):
    return recipe.get("photo") or sample_photo(recipe["category"])


def go(page, recipe_id=None):
    st.session_state.page = page
    if recipe_id:
        st.session_state.selected = recipe_id
    st.rerun()


def toggle_favorite(recipe, url, ready, favorites):
    if recipe.get("sample"):
        demo = set(st.session_state.get("sample_favorites", []))
        if recipe["id"] in demo:
            demo.remove(recipe["id"])
        else:
            demo.add(recipe["id"])
        st.session_state.sample_favorites = list(demo)
        st.rerun()
    if not ready or not st.session_state.get("uid"):
        st.info("로그인하면 찜한 요리를 내 계정에 저장할 수 있어요.")
        return
    try:
        with db_connect(url) as conn:
            if recipe["id"] in favorites:
                conn.execute("DELETE FROM hanip_favorites WHERE user_id=%s AND recipe_id=%s",
                             (st.session_state.uid, recipe["id"]))
            else:
                conn.execute("INSERT INTO hanip_favorites VALUES (%s,%s) ON CONFLICT DO NOTHING",
                             (st.session_state.uid, recipe["id"]))
        st.rerun()
    except Exception:
        st.error("찜을 저장하지 못했어요. 잠시 후 다시 눌러 주세요.")


def account(url, ready):
    st.subheader("내 계정")
    if st.session_state.get("uid"):
        st.success(f"{st.session_state.nickname}님, 반가워요!")
        if st.button("로그아웃", use_container_width=True):
            for key in ("uid", "nickname"):
                st.session_state.pop(key, None)
            st.rerun()
        return
    if not ready:
        st.info("지금은 예시 둘러보기 모드예요. 공유 저장소가 연결되면 가입할 수 있어요.")
        return
    login, register = st.tabs(["로그인", "처음 왔어요"])
    with login:
        with st.form("login", clear_on_submit=True):
            handle = st.text_input("아이디", max_chars=30).strip().lower()
            password = st.text_input("비밀번호", type="password", max_chars=128)
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
        if submitted:
            # 세션 단위 지연. 공개 서비스에는 별도의 서버 단위 속도 제한이 필요합니다.
            import time
            if time.time() < st.session_state.get("login_after", 0):
                st.warning("잠시 기다린 뒤 다시 시도해 주세요.")
            else:
                st.session_state.login_after = time.time() + 2
                try:
                    with db_connect(url) as conn:
                        user = conn.execute("SELECT * FROM hanip_users WHERE handle=%s", (handle,)).fetchone()
                    salt = user["salt"] if user else "0" * 32
                    digest = password_hash(password, salt)
                    if user and hmac.compare_digest(digest, user["password_hash"]):
                        st.session_state.uid = user["id"]
                        st.session_state.nickname = user["nickname"]
                        go("홈")
                    else:
                        st.error("아이디 또는 비밀번호를 확인해 주세요.")
                except Exception:
                    st.error("로그인에 실패했어요. 잠시 후 다시 시도해 주세요.")
    with register:
        with st.form("register", clear_on_submit=True):
            nickname = st.text_input("레시피에 표시할 이름", max_chars=20).strip()
            handle = st.text_input("새 아이디 (영문·숫자, 4~30자)", max_chars=30).strip().lower()
            password = st.text_input("새 비밀번호 (8자 이상)", type="password", max_chars=128)
            confirmation = st.text_input("비밀번호 한 번 더", type="password", max_chars=128)
            st.caption("전용 비밀번호를 사용해 주세요. 다른 사이트의 비밀번호는 쓰지 마세요.")
            submitted = st.form_submit_button("가입하고 시작", type="primary", use_container_width=True)
        if submitted:
            import re
            if not nickname or not re.fullmatch(r"[a-z0-9]{4,30}", handle):
                st.warning("이름과 아이디 형식을 확인해 주세요.")
            elif len(password) < 8 or password != confirmation:
                st.warning("비밀번호는 8자 이상이며 두 칸이 같아야 해요.")
            else:
                try:
                    uid, salt = str(uuid.uuid4()), secrets.token_hex(16)
                    with db_connect(url) as conn:
                        result = conn.execute("""INSERT INTO hanip_users (id, handle, nickname, salt, password_hash)
                            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(handle) DO NOTHING RETURNING id""",
                            (uid, handle, nickname, salt, password_hash(password, salt))).fetchone()
                    if not result:
                        st.warning("이미 사용 중인 아이디예요.")
                    else:
                        st.session_state.uid = uid
                        st.session_state.nickname = nickname
                        go("홈")
                except Exception:
                    st.error("가입을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.")


def upload(url, ready):
    st.subheader("내 요리 올리기")
    if not ready:
        st.info("공유 저장소 연결 전이라 요리를 올릴 수 없어요. 홈에서 예시를 먼저 둘러보세요.")
        return
    if not st.session_state.get("uid"):
        st.info("내 계정으로 로그인하고 나만의 요리를 공유해 주세요.")
        if st.button("로그인하러 가기", type="primary", use_container_width=True):
            go("내 공간")
        return
    st.caption("사진과 요리법은 다른 이용자에게 공개돼요. 직접 만든 사진과 글만 올려 주세요.")
    with st.form("new_recipe", clear_on_submit=False):
        photo = st.file_uploader("완성된 음식 사진 · JPG/PNG, 8MB 이하", type=["jpg", "jpeg", "png"])
        title = st.text_input("요리 이름", placeholder="우리 집 들깨수제비", max_chars=50)
        category = st.selectbox("음식 종류", list(CATEGORIES)[1:])
        minutes = st.number_input("만드는 시간 (분)", min_value=1, max_value=1440, value=20, step=5)
        servings = st.number_input("몇 인분인가요?", min_value=1, max_value=30, value=2)
        ingredients = st.text_area("재료와 양 · 한 줄에 하나씩", placeholder="감자 1개\n밀가루 200g", max_chars=4000)
        steps_text = st.text_area("만드는 순서 · 한 줄에 한 단계씩", height=180,
                                  placeholder="재료를 씻고 썰어요.\n냄비에 물을 끓여요.", max_chars=10000)
        tip = st.text_area("나만의 비법 (선택)", max_chars=1000, placeholder="우리 집에서는 마지막에 들깨가루를 넣어요.")
        submitted = st.form_submit_button("레시피 공유하기", type="primary", use_container_width=True)
        if submitted:
            steps = [line.strip() for line in steps_text.splitlines() if line.strip()]
            if not title.strip() or not ingredients.strip() or not steps or photo is None:
                st.warning("음식 사진, 요리 이름, 재료, 만드는 순서를 모두 채워 주세요.")
            elif len(steps) > 30:
                st.warning("조리 과정은 30단계 이하로 정리해 주세요.")
            else:
                try:
                    data = prepare_photo(photo.getvalue())
                    rid = str(uuid.uuid4())
                    with db_connect(url) as conn:
                        conn.execute("""INSERT INTO hanip_recipes
                        (id,user_id,title,category,minutes,servings,ingredients,steps,tip,photo)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (rid, st.session_state.uid, title.strip(), category, int(minutes), int(servings),
                         ingredients.strip(), json.dumps(steps, ensure_ascii=False), tip.strip(), data))
                    st.session_state.flash = "요리를 공유했어요! 다른 휴대폰에서도 새로고침하면 볼 수 있어요."
                    go("상세", rid)
                except ValueError as exc:
                    st.warning(str(exc))
                except Exception:
                    st.error("저장하지 못했어요. 연결을 확인하고 다시 시도해 주세요.")


def detail(recipe, url, ready, favorites):
    if st.button("← 메뉴로 돌아가기"):
        go("홈")
    st.image(photo_for(recipe), use_container_width=True)
    if recipe.get("sample"):
        st.caption("둘러보기용 예시 · 사진 대신 음식 일러스트를 사용했어요.")
    st.markdown(f"## {esc(recipe['title'])}")
    st.caption(f"{recipe['author']}님의 레시피 · {recipe['minutes']}분 · {recipe['servings']}인분")
    liked = recipe["id"] in favorites
    if st.button("♥ 찜했어요" if liked else "♡ 이 요리 찜하기", use_container_width=True):
        toggle_favorite(recipe, url, ready, favorites)
    st.markdown("### 재료")
    for index, ingredient in enumerate(recipe["ingredients"].splitlines()):
        if ingredient.strip():
            st.checkbox(ingredient.strip(), key=f"ingredient_{recipe['id']}_{index}")
    st.caption("재료 체크와 조리 진행은 현재 접속 중에만 유지돼요.")
    if recipe.get("tip"):
        with st.container(border=True):
            st.markdown("**이 요리의 한 끗 💡**")
            st.write(recipe["tip"])
    st.markdown("### 만드는 순서")
    cooking_key = f"cooking_{recipe['id']}"
    if st.button("🍳 만들기 시작", type="primary", use_container_width=True):
        st.session_state[cooking_key] = 0
    if cooking_key in st.session_state:
        index = min(st.session_state[cooking_key], len(recipe["steps"]) - 1)
        with st.container(border=True):
            st.caption(f"STEP {index + 1} / {len(recipe['steps'])}")
            st.markdown(f"### {esc(recipe['steps'][index])}")
            st.progress((index + 1) / len(recipe["steps"]))
            if index > 0 and st.button("← 이전 단계"):
                st.session_state[cooking_key] -= 1
                st.rerun()
            if index < len(recipe["steps"]) - 1:
                if st.button("다 했어요, 다음 →", type="primary", use_container_width=True):
                    st.session_state[cooking_key] += 1
                    st.rerun()
            elif st.button("요리 완성!", type="primary", use_container_width=True):
                st.success("수고했어요. 맛있게 드세요! 🍽️")
                st.balloons()
    else:
        for index, step in enumerate(recipe["steps"], 1):
            st.write(f"**{index}.** {step}")
    text = f"{recipe['title']}\n{recipe['author']}님의 레시피\n\n[재료]\n{recipe['ingredients']}\n\n[만드는 순서]\n"
    text += "\n".join(f"{i}. {s}" for i, s in enumerate(recipe["steps"], 1))
    text += f"\n\n[비법]\n{recipe.get('tip', '')}"
    st.download_button("레시피 글 저장", text.encode("utf-8-sig"), "recipe.txt", "text/plain", use_container_width=True)
    if not recipe.get("sample") and st.session_state.get("uid") == recipe.get("user_id"):
        with st.expander("내 게시물 관리"):
            confirmed = st.checkbox("삭제하면 되돌릴 수 없음을 확인했어요.")
            if st.button("이 레시피 삭제", disabled=not confirmed):
                try:
                    with db_connect(url) as conn:
                        conn.execute("DELETE FROM hanip_recipes WHERE id=%s AND user_id=%s",
                                     (recipe["id"], st.session_state.uid))
                    go("홈")
                except Exception:
                    st.error("삭제하지 못했어요. 다시 시도해 주세요.")


def normalize(value):
    return unicodedata.normalize("NFKC", value).casefold().replace(" ", "")


def matches(recipe, query, category, quick):
    searchable = normalize(" ".join(str(recipe.get(k, "")) for k in ("title", "author", "ingredients")))
    return ((category == "전체" or recipe["category"] == category)
            and normalize(query.strip()) in searchable and (not quick or recipe["minutes"] <= 20))


def main():
    st.set_page_config(page_title="한입공유 · 우리들의 레시피", page_icon="🍳", layout="centered", initial_sidebar_state="collapsed")
    st.markdown("""<style>
    :root{--mint:#087E75;--ink:#153C37;--pale:#EAF7F4;--line:#DAE9E5}
    .stApp{background:#F8FBFA;color:var(--ink)}
    .block-container{max-width:760px;padding:1.1rem 1rem 3rem}
    header[data-testid="stHeader"]{background:transparent}
    [data-testid="stSidebar"]{display:none}
    h1,h2,h3,p,label{word-break:keep-all;overflow-wrap:anywhere}
    .brand{font-size:24px;font-weight:900;letter-spacing:-1px;margin-bottom:12px}
    .hero{background:#D8F3ED;border-radius:24px;padding:23px 21px;margin:10px 0 20px}
    .hero small{color:#17645A;font-weight:700}.hero h1{font-size:29px;line-height:1.3;margin:8px 0}
    .hero p{font-size:15px;margin:4px 0;color:#38665F}
    .tag{display:inline-block;background:#FFF0C6;border-radius:8px;padding:3px 8px;color:#6F5010;font-size:12px;font-weight:700}
    div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px!important;background:white}
    .stButton button,.stDownloadButton button,.stFormSubmitButton button{min-height:46px;border-radius:13px;font-weight:700}
    button[kind="primary"],button[kind="primaryFormSubmit"]{background:#087E75;border-color:#087E75;color:white}
    .stTextInput input,.stTextArea textarea{font-size:16px!important}
    [data-testid="stImage"] img{border-radius:16px;object-fit:cover}
    @media(max-width:520px){.block-container{padding:.7rem .8rem 2rem}.hero h1{font-size:26px}
    div[data-testid="stHorizontalBlock"]{gap:.4rem}.stButton button{padding:.3rem .25rem}
    .stButton button p{font-size:14px}}
    </style>""", unsafe_allow_html=True)
    st.session_state.setdefault("page", "홈")
    try:
        url = st.secrets.get("DATABASE_URL", "")
    except Exception:
        url = ""
    url = url or os.environ.get("DATABASE_URL", "")
    ready, db_failed = False, False
    recipes = []
    if url:
        try:
            initialize_db(url)
            recipes = get_recipes(url)
            ready = True
        except Exception:
            db_failed = True
    st.markdown('<div class="brand">🍳 한입공유 <span style="font-size:13px;color:#56716C">우리들의 레시피</span></div>', unsafe_allow_html=True)
    if db_failed:
        st.warning("공유 저장소에 연결되지 않았어요. 지금은 예시만 볼 수 있어요.")
    elif not ready:
        st.caption("👀 예시 둘러보기 · 공유 저장소 연결 전")
    if ready:
        st.caption("🟢 공유 저장소 연결됨")
    nav = st.columns(4)
    for col, label in zip(nav, ["홈", "찜한 요리", "요리 올리기", "내 공간"]):
        with col:
            if st.button(label, use_container_width=True, type="primary" if st.session_state.page == label else "secondary"):
                go(label)
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    favorites = set(st.session_state.get("sample_favorites", []))
    if ready:
        try:
            favorites |= get_favorites(url, st.session_state.get("uid"))
        except Exception:
            st.warning("찜 목록을 불러오지 못했어요.")
    all_recipes = recipes + SAMPLES
    page = st.session_state.page
    if page == "요리 올리기":
        upload(url, ready)
        return
    if page == "상세":
        recipe = next((r for r in all_recipes if r["id"] == st.session_state.get("selected")), None)
        if recipe:
            detail(recipe, url, ready, favorites)
        else:
            st.info("삭제되었거나 현재 목록에 없는 레시피예요. 홈에서 다시 찾아 주세요.")
        return
    if page == "내 공간":
        account(url, ready)
        if not st.session_state.get("uid"):
            return
        st.subheader("내가 올린 요리")
        visible = [r for r in recipes if r["user_id"] == st.session_state.uid]
    elif page == "찜한 요리":
        st.subheader("다시 만들고 싶은 한입 ♥")
        visible = [r for r in all_recipes if r["id"] in favorites]
        st.caption("실제 요리 찜은 로그인 계정에 저장돼요. 예시 찜은 현재 접속 중에만 유지돼요.")
    else:
        st.markdown('<section class="hero"><small>한 사람의 비법이, 모두의 한 끼로</small><h1>오늘은 누구의 요리를<br>만들어 볼까요?</h1><p>내가 아끼는 레시피를 함께 나눠요.</p></section>', unsafe_allow_html=True)
        query = st.text_input("요리 검색", placeholder="🔎 요리 이름, 재료, 만든 사람", label_visibility="collapsed", max_chars=100)
        category = st.pills("어떤 요리를 찾나요?", [f"{icon} {name}" for name, icon in CATEGORIES.items()],
                            default="🍽️ 전체", selection_mode="single", label_visibility="collapsed")
        chosen = category.split(" ", 1)[1] if category else "전체"
        quick = st.toggle("20분 이내로 뚝딱", value=False)
        order = st.selectbox("정렬", ["최근 올라온 순", "빠르게 만드는 순"], label_visibility="collapsed")
        visible = [r for r in all_recipes if matches(r, query, chosen, quick)]
        if order == "빠르게 만드는 순":
            visible.sort(key=lambda r: r["minutes"])
        st.markdown(f"### 함께 나누는 레시피 · {len(visible)}")
        if st.button("↻ 새 레시피 확인", use_container_width=True):
            st.rerun()
    if not visible:
        st.info("아직 요리가 없어요. 다른 메뉴를 고르거나 첫 레시피를 올려 주세요.")
    # 휴대폰에서도 사진과 이름을 넉넉하게 읽도록 카드는 세로로 배치합니다.
    for recipe in visible:
        with st.container(border=True):
            st.image(photo_for(recipe), use_container_width=True)
            if recipe.get("sample"):
                st.markdown('<span class="tag">예시 레시피 · 음식 일러스트</span>', unsafe_allow_html=True)
            st.markdown(f"### {esc(recipe['title'])}")
            st.caption(f"{recipe['author']}님의 레시피 · {recipe['category']} · {recipe['minutes']}분 · {recipe['servings']}인분")
            a, b = st.columns([3, 1])
            with a:
                if st.button("레시피 보기 →", key="open_"+recipe["id"], use_container_width=True):
                    go("상세", recipe["id"])
            with b:
                if st.button("♥" if recipe["id"] in favorites else "♡ 찜", key="fav_"+recipe["id"], use_container_width=True):
                    toggle_favorite(recipe, url, ready, favorites)
    st.caption("한입공유 · 음식 알레르기와 재료의 익힘 정도를 확인해 주세요.")


if __name__ == "__main__":
    main()
