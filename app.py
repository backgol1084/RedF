import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="RedF", layout="centered")
st.title("RedF")


@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


supabase = init_supabase()

with st.form("redf_form", clear_on_submit=True):
    title = st.text_input("제목")
    content = st.text_area("내용")
    submitted = st.form_submit_button("저장")

    if submitted:
        if title.strip():
            supabase.table("redf_items").insert(
                {"title": title.strip(), "content": content.strip()}
            ).execute()
            st.success("저장되었습니다.")
            st.rerun()
        else:
            st.warning("제목을 입력해 주세요.")

st.subheader("등록된 목록")
response = (
    supabase.table("redf_items")
    .select("*")
    .order("id", desc=True)
    .execute()
)

for row in response.data:
    with st.container(border=True):
        st.markdown(f"**{row['title']}**")
        if row.get("content"):
            st.write(row["content"])
