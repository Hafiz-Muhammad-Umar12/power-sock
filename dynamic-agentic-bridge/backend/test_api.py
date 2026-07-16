import anthropic, os
from dotenv import load_dotenv

load_dotenv(override=True)
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
msg = client.messages.create(
    model='claude-sonnet-4-5',
    max_tokens=50,
    messages=[{'role': 'user', 'content': 'say hello'}]
)
print(msg.content)