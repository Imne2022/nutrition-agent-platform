
import os

import requests
import streamlit as st


API_BASE_URL = os.getenv(
    "NUTRITION_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

ANSWER_ENDPOINT = f"{API_BASE_URL}/api/answer"


st.set_page_config(
    page_title="Nutrition Evidence Assistant",
    page_icon="🥗",
    layout="wide",
)

st.title("🥗 Nutrition Evidence Assistant")
st.write(
    "Ask a nutrition question and explore the source sentences "
    "retrieved from your indexed evidence."
)

st.info(
    "Answers are extracted from retrieved source text. "
    "This tool does not generate medical advice or diagnose conditions."
)

with st.form("nutrition_question_form"):
    question = st.text_area(
        "Your question",
        placeholder="Example: What are the benefits of green tea?",
        max_chars=1000,
        height=100,
    )

    top_k = st.slider(
        "Evidence chunks to retrieve",
        min_value=1,
        max_value=20,
        value=5,
    )

    submitted = st.form_submit_button(
        "Find evidence",
        type="primary",
    )


if submitted:
    question = question.strip()

    if not question:
        st.warning("Enter a question before searching.")
    else:
        payload = {
            "question": question,
            "top_k": top_k,
        }

        with st.spinner("Retrieving and checking evidence..."):
            try:
                response = requests.post(
                    ANSWER_ENDPOINT,
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()

            except requests.exceptions.ConnectionError:
                st.error(
                    "Cannot connect to the Nutrition Evidence API. "
                    "Start FastAPI in another terminal and try again."
                )
                st.stop()

            except requests.exceptions.Timeout:
                st.error(
                    "The API request timed out. Try again, "
                    "or check the FastAPI terminal."
                )
                st.stop()

            except requests.exceptions.HTTPError as exc:
                status_code = (
                    exc.response.status_code
                    if exc.response is not None
                    else "unknown"
                )
                detail = "The API could not process this question."

                if exc.response is not None:
                    try:
                        detail = exc.response.json().get(
                            "detail",
                            detail,
                        )
                    except ValueError:
                        pass

                st.error(f"API error ({status_code}): {detail}")
                st.stop()

            except requests.exceptions.RequestException as exc:
                st.error(f"Request failed: {exc}")
                st.stop()

        st.subheader("Answer")

        if data.get("insufficient_evidence", True):
            st.warning(
                "Insufficient evidence: no suitable supporting "
                "sentences were found in the retrieved sources. "
                "Try rephrasing the question."
            )
        else:
            answer = data.get("answer")

            if answer:
                st.write(answer)
            else:
                st.warning("The API returned no answer text.")

        sources = data.get("sources", [])

        st.subheader(f"Supporting evidence ({len(sources)})")

        if not sources:
            st.caption("No supporting source sentences were returned.")
        else:
            for index, source_item in enumerate(sources, start=1):
                with st.expander(
                    f"Evidence {index}: "
                    f"{source_item.get('article_title') or 'Source document'}"
                ):
                    st.write(source_item.get("text", ""))

                    source = source_item.get("source", "")
                    if source.startswith(("https://", "http://")):
                        st.markdown(f"[Open original source]({source})")
                    elif source:
                        st.caption(f"Source citation: {source}")

                    similarity = source_item.get("similarity")
                    if similarity is not None:
                        st.caption(
                            f"Retrieval similarity: {similarity:.4f}"
                        )

        st.caption(
            "Similarity is a retrieval score, not a measure of "
            "medical certainty or factual correctness."
        )

st.divider()
st.caption("Nutrition Evidence Assistant · Extractive retrieval UI")
