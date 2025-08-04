from setuptools import setup, find_packages

setup(
    name="webqa_agent",
    version="0.0.1",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "playwright==1.52.0",
        "pillow",
        "pydantic",
        "langgraph",
        "langchain-openai",
        "langchain",
        "openai",
        "python-dotenv",
        "pycryptodome",
        "tldextract",
        "requests",
        "html2text",
        "oss2",
        "requests_toolbelt",
        "jinja2"
    ],
    python_requires='>=3.10',
)


