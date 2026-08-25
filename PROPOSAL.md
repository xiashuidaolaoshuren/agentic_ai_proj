# Project Proposal: AI News Research Agent

## 1. Introduction
In the rapidly evolving field of Artificial Intelligence, staying updated with curated news, open-source projects, trending models, practitioner experience, and learning resources is a significant challenge. These signals are scattered across platforms such as Juya, GitHub, Hugging Face, Zhihu, and Bilibili. This project proposes an agentic AI solution to automate their discovery, kind-aware ranking, and summarization for personal learning and professional development.

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
- **Multi-Source Discovery**: Distinct roles for Juya (default bulletin), Hugging Face (opt-in trending models), GitHub (opt-in trending repos), Zhihu (opt-in practitioner insights), and Bilibili (opt-in video).
- **Intelligent Ranking**: Kind-aware scores and segmented mixed digests; freshness, relevance, and learning value within each source kind.
- **Contextual Summarization**: Summaries in the source's original language, including "why it matters" and background knowledge requirements.
- **Interactive Follow-up**: A chatbot interface that allows users to ask questions about the generated digest.
- **Inspectable Traces**: Local storage of source metadata and ranking decisions for transparency and verification.

## 4. High-Level Architecture
The system follows a modular architecture to ensure flexibility and maintainability:
- **Chat Interface**: A Gradio-based local UI for user interaction.
- **Agent Orchestrator**: Powered by **LangGraph** to manage stateful, multi-step workflows.
- **Source Connectors**: Dedicated modules for Juya, Hugging Face, GitHub, Zhihu, and Bilibili, each with a distinct product job.
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
- **Milestone 5: Source Role Split**: First-class Juya connector, GitHub trending-repo re-purpose, Juya-only default, kind-aware segmented ranking (see `docs/adr/0001-source-role-split.md`).
- **Milestone 6: AI Ecosystem & Practitioner Signals**: Add Hugging Face model-momentum and Zhihu practitioner-insight connectors, with source-native ranking and full interface parity; defer arXiv and generic RSS (see `docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md`).
- **Milestone 7: Advanced Features**: Scheduled digests, long-term memory, and automated quality evaluation.

## 7. Expected Outcomes
- A functional AI agent that significantly reduces the time spent on AI research.
- A robust, modular codebase that serves as a foundation for further agentic AI experiments.
- A practical demonstration of core agentic patterns: tool use, stateful orchestration, and RAG-lite follow-up.
