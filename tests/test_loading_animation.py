import time

from webqa_agent.utils.loading_animation import LoadingAnimation

with LoadingAnimation("Testing..."):
    print("This is a test message.")
    time.sleep(5)
