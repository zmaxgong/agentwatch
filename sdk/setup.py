"""Setup for AgentWatch SDK."""

from setuptools import setup, find_packages

setup(
    name="agentwatch",
    version="0.1.0",
    description="Observability SDK for AI agents — monitor cost, hallucinations, security, and drift",
    long_description=open("../README.md").read() if __import__("os").path.exists("../README.md") else "",
    long_description_content_type="text/markdown",
    author="Tandm Labs",
    author_email="hello@tandmlabs.com",
    url="https://github.com/zmaxgong/agentwatch",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],
    extras_require={
        "anthropic": ["anthropic>=0.40.0"],
        "all": ["anthropic>=0.40.0"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries",
    ],
)
