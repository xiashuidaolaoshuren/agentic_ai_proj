# Project Proposal: AI News Research Agent

## 1. Introduction
In the rapidly evolving field of Artificial Intelligence, staying updated with the latest model publications, applications, and development trends is a significant challenge. Information is scattered across various platforms such as GitHub, Bilibili, arXiv, and Hugging Face. This project proposes an agentic AI solution to automate the discovery, ranking, and summarization of AI news for personal learning and professional development.

## 2. Problem Statement
Manual tracking of AI news is time-consuming and often leads to information overload. Users need a centralized, intelligent system that can:
- Discover relevant AI signals from diverse sources.
- Filter out noise and rank items based on learning value.
- Provide concise summaries and actionable follow-up suggestions.
- Support interactive follow-up questions for deeper understanding.

## 3. Proposed Solution: AI News Research Agent
The AI News Research Agent is a local-first, on-demand chatbot designed to be a personal AI learning companion. It leverages agentic workflows to orchestrate the process of news discovery and summarization.

### Key Features
- **On-Demand Digest**: Generate a ranked AI news digest upon request.
- **Multi-Source Discovery**: Initial support for GitHub and Bilibili, with a modular design for future expansion (arXiv, Hugging Face, etc.).
- **Intelligent Ranking**: Scores items based on freshness, relevance, and learning value.
- **Contextual Summarization**: Summaries in the source's original language, including "why it matters" and background knowledge requirements.
- **Interactive Follow-up**: A chatbot interface that allows users to ask questions about the generated digest.
- **Inspectable Traces**: Local storage of source metadata and ranking decisions for transparency and verification.

## 4. High-Level Architecture
The system follows a modular architecture to ensure flexibility and maintainability:
- **Chat Interface**: A Gradio-based local UI for user interaction.
- **Agent Orchestrator**: Powered by **LangGraph** to manage stateful, multi-step workflows.
- **Source Connectors**: Dedicated modules for interfacing with GitHub and Bilibili.
- **Ranking & Summarization Layers**: Logic for filtering and generating content using LLMs.
- **Storage Layer**: SQLite for local persistence of digests and metadata.
- **Interface Adapters**: Designed to support future integrations like **OpenClaw**.

## 5. Tech Stack
- **Language**: Python
- **Orchestration**: LangGraph
- **LLM Framework**: LangChain (for abstractions)
- **UI**: Gradio
- **Database**: SQLite
- **Model Access**: OpenAI-compatible API

## 6. Project Milestones
- **Milestone 1: Local Digest MVP**: Core agent workflow with GitHub and Bilibili support, Gradio UI, and local storage.
- **Milestone 2: LLM Tool Usage Layer**: Structured tool registry and bounded LangGraph tool-calling loop for follow-up chat and source exploration.
- **Milestone 3: OpenClaw Adapter**: Exposing the agent as a tool within the OpenClaw assistant gateway.
- **Milestone 4: Pydantic Schema + LangChain `@tool` Registry Migration**: Migrate domain models and tool schemas to Pydantic v2 and the tool registry to LangChain's `@tool` workflow.
- **Milestone 5: Source Expansion**: Adding connectors for arXiv, Hugging Face, and RSS feeds.
- **Milestone 6: Advanced Features**: Scheduled digests, long-term memory, and automated quality evaluation.

## 7. Expected Outcomes
- A functional AI agent that significantly reduces the time spent on AI research.
- A robust, modular codebase that serves as a foundation for further agentic AI experiments.
- A practical demonstration of core agentic patterns: tool use, stateful orchestration, and RAG-lite follow-up.
