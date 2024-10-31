
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import os
from youtube_transcript_api import YouTubeTranscriptApi
import time
import re
import tiktoken
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.api_core.exceptions import ResourceExhausted
# Load environment variables from a .env file
load_dotenv()

genai.configure(api_key='api-key-here')

@retry(
    stop=stop_after_attempt(3),
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
You are an expert content writer and storyteller with years of experience in creating viral blog posts. Your task is to transform the input content into a captivating, human-like blog post that feels personally written and connects deeply with readers.

Guidelines for Creating an Authentic, Engaging Blog Post:

1. Voice & Personality:
   - Write as if you're having a coffee chat with the reader
   - Include personal observations and insights
   - Use "I", "we", and "you" to create connection
   - Add thoughtful rhetorical questions to engage readers
   - Include relevant personal anecdotes or examples

2. Enhanced Structure:
   - Hook: Start with a powerful personal story or provocative question
   - Introduction: Create an emotional connection with the reader's pain points
   - Story Arc: Maintain narrative tension throughout
   - Strategic Cliffhangers: Keep readers engaged between sections
   - Memorable Conclusion: End with inspiration or call-to-action

3. Human Touch Elements:
   - Add occasional conversational asides (e.g., "Now, here's the interesting part...")
   - Include relatable real-world examples
   - Share practical tips from personal experience
   - Address potential reader objections naturally
   - Use humor and wit where appropriate

4. Engagement Boosters:
   - Create "Aha!" moments
   - Include surprising statistics or counterintuitive insights
   - Add social proof through expert quotes or case studies
   - Use power words and emotional triggers
   - Create shareable, quotable moments

5. Modern Content Optimization:
   - Write scannable content with varied paragraph lengths
   - Use bucket brigades to maintain flow
   - Include tweet-worthy quotes
   - Add content upgrades or bonus tips
   - Suggest related resources

6. Visual Flow:
   - Use descriptive scene-setting
   - Include sensory details
   - Suggest relevant image placements
   - Break up text with varied formatting
   - Create visual hierarchy with subheadings

7. Viral Elements:
   - Include controversial or debate-worthy points
   - Add "share-worthy" statistics or facts
   - Create memorable metaphors
   - Include practical takeaways
   - End with discussion-provoking questions

8. Reader Experience:
   - Address common objections preemptively
   - Include FAQs in conversational style
   - Add expert tips and insider secrets
   - Provide actionable next steps
   - Create FOMO (Fear of Missing Out) elements

9. Content Enhancement:
   - Add relevant industry trends
   - Include success stories or case studies
   - Provide practical implementation steps
   - Share common mistakes to avoid
   - Offer exclusive insights

10. SEO & Readability:
    - Natural keyword integration: {keywords}
    - Use power words and emotional triggers
    - Create skimmable sections
    - Include meta description and title suggestions
    - Optimize for featured snippets

Tone Guidelines:
- Maintain a {tone} voice throughout
- Balance expertise with accessibility
- Use conversational language
- Show personality and authenticity
- Be empathetic and understanding

Length: Aim for {word_count} words while maintaining quality and engagement

Please transform the following input into a captivating, human-like blog post that readers won't be able to resist sharing:

{input_text}

Remember: Write as if you're the world's most engaging storyteller sharing invaluable insights with a friend. Make every word count and every paragraph impossible to skip.
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
def get_transcript(youtube_video_url):
    """Get transcript from YouTube video with verification dropdown"""
    try:
        video_id = youtube_video_url.split("=")[1]
        transcript_text = YouTubeTranscriptApi.get_transcript(video_id, languages=['en-IN', 'en', 'hi'])
        transcript = " ".join([entry["text"] for entry in transcript_text])
        
        # Store transcript in session state for verification
        st.session_state.current_transcript = transcript
        
        # Add expandable section to verify transcript
        with st.expander("🔍 View Raw Transcript", expanded=False):
            st.markdown("### Raw Transcript")
            st.markdown("*Verify the transcript before generating the blog post:*")
            
            # Display transcript with scroll
            st.markdown(
                f"""
                <div style="max-height: 300px; overflow-y: scroll; padding: 10px; 
                border: 1px solid #ccc; border-radius: 5px; background-color: #f5f5f5;">
                {transcript}
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            # Add word count info
            word_count = len(transcript.split())
            st.info(f"📝 Word Count: {word_count} words")
            
            # Add transcript quality warning if needed
            if word_count < 100:
                st.warning("⚠️ The transcript seems quite short. This might affect the quality of the generated blog post.")
        
        return transcript
        
    except Exception as e:
        st.error(f"Error retrieving transcript: {e}")
        return None

class ResponseManager:
    def __init__(self, model):
        self.model = model
        self.MAX_TOKENS = 8192  # Adjust based on the model's limit
        self.BATCH_SIZE = 1000  # Adjust as needed

    def count_tokens(self, text: str) -> int:
        try:
            encoding = tiktoken.encoding_for_model("gemini-1.5-flash")  # Use the correct model name
            return len(encoding.encode(text))
        except Exception:
            return len(text.split()) * 1.3  # Fallback approximation

    def generate_response(self, prompt, temperature, placeholder):
        full_response = ""
        continuation_prompt = "\nPlease continue from where you left off..."
        current_prompt = prompt

        try:
            while True:
                remaining_tokens = self.MAX_TOKENS - self.count_tokens(full_response)
                tokens_to_generate = min(self.BATCH_SIZE, remaining_tokens)

                response = self.model.generate_content(
                    current_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=tokens_to_generate,
                    ),
                    stream=True
                )

                batch_response = ""
                for chunk in response:
                    if chunk.text:
                        batch_response += chunk.text
                        full_response += chunk.text
                        placeholder.markdown(full_response + "▌")
                        time.sleep(0.01)

                if batch_response.strip().endswith((".", "!", "?", "\n")) or \
                   len(batch_response.strip()) < tokens_to_generate * 0.9:
                    break

                current_prompt = full_response + continuation_prompt

            return full_response

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            return f"Error generating response: {str(e)}"

def generate_blog_post(input_text, tone, keywords, length):
    """Generate a complete blog post using ResponseManager"""
    word_count = LENGTH_OPTIONS[length]
    model = genai.GenerativeModel("gemini-1.5-flash")
    response_manager = ResponseManager(model)
    
    try:
        # Show processing status
        status_container = st.empty()
        status_container.info("🔄 Starting blog post generation...")
        
        # Prepare the prompt
        prompt = f"""
        {base_prompt_template}
        
        Use the following input to create a single, cohesive blog post:
        {input_text}
        
        Ensure the blog post:
        - Has a consistent {tone} tone
        - Incorporates these keywords: {', '.join(keywords)}
        - Is approximately {word_count} words long
        - Flows smoothly and reads as a single, coherent piece
        """
        
        # Generate content with ResponseManager
        status_container.info("🎯 Generating blog post...")
        blog_post = response_manager.generate_response(prompt, temperature=0.7, placeholder=status_container)
        
        status_container.success("✨ Blog post generated successfully!")
        
        return blog_post
        
    except Exception as e:
        st.error(f"❌ Error generating blog post: {str(e)}")
        return None

# Streamlit UI with progress tracking
def main():
    st.set_page_config(page_title="BlogBrain Genius AI", layout="wide")
    
    # Initialize session state
    if 'blog_post' not in st.session_state:
        st.session_state.blog_post = None
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'cancel_generation' not in st.session_state:
        st.session_state.cancel_generation = False
    
    st.title("✍️ BlogBrain Genius AI: Video to Blog Alchemist")
    
    # Input method selection
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
        st.markdown("<h1 style='text-align: center; color: #4A90E2;'>🧠 BlogBrain Genius AI</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Transform Content into Engaging Blog Posts</p>", unsafe_allow_html=True)
        st.markdown("---")
        tone = st.selectbox("Select tone:", TONE_OPTIONS)
        keywords = st.text_input("Enter keywords (comma-separated):")
        length = st.selectbox("Select length:", list(LENGTH_OPTIONS.keys()))
    
    # Generate button
    if st.button("Generate Blog Post") and input_text:
        st.session_state.processing = True
        st.session_state.cancel_generation = False
        try:
            with st.spinner("Generating a single, comprehensive blog post..."):
                # Add a cancel button
                if st.button("Cancel Generation"):
                    st.session_state.cancel_generation = True
                
                blog_post = generate_blog_post(
                    input_text,
                    tone,
                    keywords.split(",") if keywords else [],
                    length
                )
                
                if blog_post and not st.session_state.cancel_generation:
                    st.session_state.blog_post = blog_post
                    st.success("Blog post generated successfully!")
                elif st.session_state.cancel_generation:
                    st.warning("Blog post generation was cancelled.")
                else:
                    st.error("Failed to generate the blog post. Please try again later.")
        except Exception as e:
            st.error(f"An unexpected error occurred: {str(e)}")
        finally:
            st.session_state.processing = False
    
    # Display results
    if st.session_state.blog_post:
        st.markdown(st.session_state.blog_post)
        col1, col2 = st.columns(2)
        with col1:
            if st.download_button(
                "Download Blog Post",
                st.session_state.blog_post,
                "blog_post.md",
                "text/markdown"
            ):
                st.success("Blog post downloaded successfully!")
        with col2:
            if st.button("Reset"):
                st.session_state.blog_post = None
                st.experimental_rerun()

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
