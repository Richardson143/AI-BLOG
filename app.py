
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import os
from youtube_transcript_api import YouTubeTranscriptApi
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted
# Load environment variables from a .env file
load_dotenv()

# Configure the Google Generative AI client with the API key from environment variables
# genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
genai.configure(api_key='AIzaSyBMb20Nck_BV_4297NnxlEju73UL5vsvYY')

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(ResourceExhausted),
    reraise=True
)
def generate_content_with_retry(model, prompt):
    time.sleep(2)  # Increased delay between API calls
    try:
        return model.generate_content(prompt)
    except ResourceExhausted as e:
        st.warning(f"API quota exceeded. Retrying in a moment... ({e})")
        raise e

# Define the base prompt template
base_prompt_template = '''
You are an AI assistant specializing in transforming long-form content, such as YouTube video transcripts or user-provided text, into a single, cohesive, and engaging blog post. Your task is to create a comprehensive blog post that captures the essence of the entire input while enriching it with additional information, insights, and a conversational touch.

Guidelines for the Blog Post:

1. Structure:
   - Title: Create an engaging title for the blog post.
   - Meta Description: Write a compelling 150-160 character meta description for SEO.
   - Introduction: Briefly introduce the topic and hook the reader.
   - Main Body: Divide into relevant sections with subheadings. Ensure smooth transitions between sections.
   - Conclusion: Summarize key points and provide a call-to-action.

2. Content Enhancement:
   - Synthesize information from all parts of the input to create a coherent narrative.
   - Provide additional explanations, examples, or related information to enrich the content.
   - Include interesting anecdotes or expert opinions to add depth and credibility.

3. Engagement:
   - Use a {tone} tone consistently throughout the post.
   - Include relevant descriptions of potential visuals or infographics.
   - Structure the post for easy readability using subheadings, bullet points, and short paragraphs.

4. SEO Optimization:
   - Naturally incorporate these keywords: {keywords}
   - Use variations and related terms to avoid keyword stuffing.
   - Implement proper heading structure (H1 for title, H2 for main sections, H3 for subsections).

5. Length and Style:
   - Aim for a total of approximately {word_count} words for the entire blog post.
   - Use varied sentence structures and paragraph lengths for better flow.
   - Incorporate rhetorical devices like analogies, metaphors, or storytelling elements where appropriate.

6. Cohesion:
   - Ensure that all parts of the blog post connect logically and flow smoothly.
   - Use transitional phrases to link different sections and ideas.
   - Maintain consistent themes and arguments throughout the post.

7. Formatting:
   - Use appropriate HTML tags for headings (h1, h2, h3), lists (ul, ol), and emphasis (strong, em).
   - Suggest places to break up text with [IMAGE PLACEHOLDER] or [VIDEO EMBED PLACEHOLDER] tags.
   - Include a table of contents for longer articles.

8. Additional Elements:
   - Create a "Key Takeaways" or "TL;DR" section for quick reference.
   - Suggest pull quotes or highlight boxes for important information.
   - If applicable, include a section addressing common questions or misconceptions about the topic.

Important: Create only ONE cohesive blog post that covers all the main points from the entire input. Ensure that the final output is a single, well-structured article, not multiple separate posts.

Please create a single, detailed, and engaging blog post based on the following input:

{input_text}

Remember to maintain a {tone} tone throughout the post and aim for a total of {word_count} words for the entire article.
'''

# Expanded tone options
TONE_OPTIONS = [
    "Professional", "Casual", "Humorous", "Inspirational", "Educational", 
    "Conversational", "Formal", "Enthusiastic", "Empathetic", "Authoritative"
]

# Article length options
LENGTH_OPTIONS = {
    "Medium (1000-1500 words)": 1250,
    "Long (1500-2500 words)": 2000,
    "Extra Long (2500-3500 words)": 3000,
    "Comprehensive (3500-5000 words)": 4250
}

# Function to extract video ID from various YouTube URL formats
def extract_video_id(url):
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?(?:embed\/)?(?:v\/)?(?:shorts\/)?(?:live\/)?(?:feature=player_embedded&v=)?([^?&"\'>]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

import threading
# Cache for storing processed data
cache = {}
cache_lock = threading.Lock()

# Optimized transcript fetching with caching
@st.cache_data
def get_transcript(youtube_video_url, max_retries=3, delay=2):
    video_id = extract_video_id(youtube_video_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL")
    
    if video_id in cache:
        return cache[video_id]
        
    for attempt in range(max_retries):
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            text = " ".join([entry["text"] for entry in transcript])
            with cache_lock:
                cache[video_id] = text
            return text
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay)

# Function to chunk long text
def chunk_text(text, chunk_size=4000, overlap=500):
    # Only chunk if text is longer than chunk_size
    if len(text) <= chunk_size:
        return [text]
        
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        
        # Find the nearest sentence end
        if end < len(text):
            end = text.rfind('.', start, end) + 1
            if end <= start:
                end = start + chunk_size
                
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        
    return chunks

# Function to generate blog post using Gemini AI model with retries
def generate_blog_post(input_text, tone, keywords, length):
    word_count = LENGTH_OPTIONS[length]
    chunks = chunk_text(input_text)
    model = genai.GenerativeModel("gemini-1.5-flash")

    all_content = []
    for i, chunk in enumerate(chunks):
        chunk_prompt = f"""
        Analyze the following part of content and extract key points, main ideas, and important details:
        
        {chunk}
        
        Provide a concise summary of this part, highlighting the most important information.
        """
        try:
            response = generate_content_with_retry(model, chunk_prompt)
            all_content.append(response.text)
        except Exception as e:
            st.error(f"Error processing chunk {i+1}: {str(e)}")
            return None
    
    final_prompt = base_prompt_template.format(
        tone=tone,
        keywords=', '.join(keywords),
        word_count=word_count,
        input_text='\n'.join(all_content)
    )

    # final_prompt = f"""
    # Create a single, cohesive blog post based on the following information:
    # {' '.join(all_content)}

    # Guidelines:
    # 1. Create a unified narrative covering all main points.
    # 2. Use a {tone} tone throughout.
    # 3. Incorporate these keywords naturally: {', '.join(keywords)}
    # 4. Aim for approximately {word_count} words.
    # 5. Include an introduction, well-structured body, and conclusion.
    # 6. Use subheadings to organize content.
    # 7. Ensure smooth transitions between topics.

    # Write the complete blog post now, maintaining a cohesive structure throughout.
    # """

    try:
        final_response = generate_content_with_retry(model, final_prompt)
        return final_response.text
    except Exception as e:
        st.error(f"Error generating final blog post: {str(e)}")
        return None


# Streamlit UI with progress tracking
def main():
    st.set_page_config(page_title="AI Blog Post Generator", layout="wide")
    
    # Initialize session state
    if 'blog_post' not in st.session_state:
        st.session_state.blog_post = None
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    
    st.title("✍️ AI Blog Post Generator")
    
    # Input method selection with proper state management
    input_method = st.radio("Choose input method:", ("YouTube Video", "Custom Text"))
    
    input_text = ""
    if input_method == "YouTube Video":
        youtube_url = st.text_input("Enter YouTube URL:")
        if youtube_url and not st.session_state.processing:
            try:
                with st.spinner("Fetching transcript..."):
                    input_text = get_transcript(youtube_url)
            except Exception as e:
                st.error(f"Error: {str(e)}")
    else:
        input_text = st.text_area("Enter your content:", height=200)
    
    # Sidebar options
    with st.sidebar:
        tone = st.selectbox("Select tone:", TONE_OPTIONS)
        keywords = st.text_input("Enter keywords (comma-separated):")
        length = st.selectbox("Select length:", list(LENGTH_OPTIONS.keys()))
    
    if st.button("Generate Blog Post") and input_text:
        st.session_state.processing = True
        try:
            with st.spinner("Generating a single, comprehensive blog post..."):
                blog_post = generate_blog_post(
                    input_text,
                    tone,
                    keywords.split(",") if keywords else [],
                    length
                )
            if blog_post:
                st.session_state.blog_post = blog_post
                st.success("Blog post generated successfully!")
            else:
                st.error("Failed to generate the blog post. Please try again later.")
        except Exception as e:
            st.error(f"An unexpected error occurred: {str(e)}")
        finally:
            st.session_state.processing = False
    
    # Display results
    if st.session_state.blog_post:
        st.markdown(st.session_state.blog_post)
        st.download_button(
            "Download Blog Post",
            st.session_state.blog_post,
            "blog_post.md",
            "text/markdown"
        )

if __name__ == "__main__":
    main()

# Sidebar with creator information
st.sidebar.markdown("---")
st.sidebar.title("About the Creator")
st.sidebar.info("""
    Designed by Richardson Gunde 🎨
    
    This advanced application uses AI to generate a single, comprehensive blog post based on long-form content from YouTube videos or user input.
    
    🔗 [LinkedIn](https://www.linkedin.com/in/richardson-gunde)
    📧 [Email](mailto:gunderichardson@gmail.com)
""")

st.markdown("""
    ---
    :green[This advanced app leverages the power of Google's Gemini AI to generate a single, detailed, SEO-optimized long-form blog post from YouTube videos or custom text. 
    It handles extensive content while ensuring a cohesive output.]
""")
