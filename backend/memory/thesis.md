# Academic Work & PhD Aspirations

## CS 5374 — Software Verification & Validation (Dr. Akbar Siami Namin)

**The Project:** Jack is the primary technical lead on an automated adversarial testing framework for LLM robustness. The project tests whether AI assistants can be socially engineered into revealing a protected 12-word BIP-39 seed phrase through multi-turn conversation. Teammates: Blake Moos, Ismael Burgos.

**Architecture:** LangGraph-based multi-agent system — an AI attacker generates social engineering prompts, a target model tries to protect the secret, and a judge evaluates breach severity. Uses LangSmith for tracing. Tested ~90 automated trials across 10+ models including Gemini 3.1 Flash-Lite, Gemini 3.1 Pro, Claude Sonnet/Haiku/Opus, Nous-Hermes 2 10.7B, Mistral 7B, llama3.2:3b.

**Novel findings (genuinely publishable according to Dr. Namin):**
- Chain-of-thought side-channel evidence: Models recite secrets internally while suppressing output. The "crunch→rustle" vocabulary swap and CRYSTAL flinch are novel findings.
- Active suppression is more visible than passive leakage — the act of hiding IS the detectable signal.
- Conditional disclosure (v5_auth) is catastrophically weak vs. absolute prohibition under controlled conditions.
- Prompt engineering (v7_hardened) can rescue some models but there's a capability floor below which nothing helps (Mistral 7B case).
- False memory context bleed is a novel mechanism (observed in Gemini 3.1 Flash-Lite).
- The LLM judge itself failed on Day 1 — scored a full breach as only 6/10 PARTIAL_LEAK.

**Status:** Post-midterm phase. Final report and presentation due approximately late April 2026.

## CS 5363 — Software Project Management
- Exam 1: 14/16. Exam 2: March 31, 2026 (scope and budget). Final exam: non-cumulative.
- Class Practice 3 (completed): Project planning document for fictional Pet Health Management System.

## Logic for Computer Scientists (Incomplete — Resolved Feb 2026)
Retook the final after receiving an incomplete the prior semester.

## Dr. Namin & PhD

**Who Dr. Namin is:** Full Professor at TTU. Research interests: Trustworthy/Agentic AI, LLM/NLP, Cybersecurity, Software Testing. h-index 34, 9,493 citations. Fulbright Scholar (Spring 2025, Austria). Funded by NSF and ONR. Active NSF award (#2319802).

**The Meeting (March 24, 2026):** Key outcomes:
1. Namin said Jack's work is publishable.
2. He has a grant proposal in the works and could potentially fund Jack by the time he finishes his MS.
3. He offered to work with Jack on a master's thesis.
4. He wants Jack to do an editing pass on a book he's writing.
5. He needs Jack for a DARPA project specifically because he needs an American citizen.

**Thesis Proposal:** "Multi-Agent Adversarial Testing of AI System Trustworthiness"
- Chapter 1: Current V&V project (side-channel analysis)
- Chapter 2: Adversarial code review using competing AI agents — MAAT framework
- Chapter 3: Counter-persuasion training for LLM robustness
- Chapter 4: Co-evolving attack/defense agents
- Each chapter designed to produce an independently publishable paper

## MAAT — Multi-Agent Adversarial Trustworthiness Framework

Four-agent pipeline — Generator (creates code), Finder (identifies vulnerabilities), Adversary (challenges findings), Referee (final verdict). Plus programmatic security detector layer.

Key results (27+ trials):
- Sonnet finds 6.8x more issues than Gemini Flash on same code
- Same-model adversarial review FAILS: Gemini 3.1 Pro killed 100% of its own findings
- Multi-agent adversarial review requires model diversity to be effective — core thesis contribution
- Temperature 0.7 is optimal Finder temperature (validated experimentally)

Tech: Python, LangGraph, LangSmith, Ollama, Gemini/Claude/OpenAI APIs. Directory: ~/Desktop/projects/adversarial-trust/
