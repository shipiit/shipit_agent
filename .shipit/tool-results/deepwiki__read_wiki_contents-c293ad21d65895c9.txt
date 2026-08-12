# Page: Overview

# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.release-please-manifest.json](.release-please-manifest.json)
- [.stats.yml](.stats.yml)
- [CHANGELOG.md](CHANGELOG.md)
- [README.md](README.md)
- [api.md](api.md)
- [pyproject.toml](pyproject.toml)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_version.py](src/openai/_version.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



The OpenAI Python SDK is the official Python client library for accessing the OpenAI REST API. It provides type-safe, idiomatic Python interfaces for all OpenAI API endpoints, supporting both synchronous and asynchronous execution models. The library is generated from OpenAI's OpenAPI specification using Stainless and targets Python 3.10 and above.

This page introduces the SDK's architecture, core concepts, and key components. For installation and configuration details, see [Installation and Setup](#2). For API-specific documentation, see [API Resources and Endpoints](#4). For type system details, see [Data Types and Type System](#5).

## Library Purpose and Scope

The SDK serves three primary functions:

1.  **API Client**: Provides `OpenAI`, `AsyncOpenAI`, `AzureOpenAI`, and `BedrockOpenAI` client classes that manage HTTP communication, authentication, retries, and error handling. [src/openai/_client.py:106-258](), [src/openai/lib/azure.py:101-200](), [src/openai/lib/bedrock.py:114-175]()
2.  **Type System**: Offers comprehensive type definitions for all request params and response fields, enabling IDE autocomplete and static type checking. [README.md:6-9](), [src/openai/types/__init__.py]()
3.  **Developer Experience**: Implements convenience features including streaming, auto-pagination, file uploads, and structured output parsing. [src/openai/_streaming.py](), [src/openai/_base_client.py:182-241]()

**Sources:** [pyproject.toml:1-6](), [README.md:1-10](), [src/openai/_client.py:106-258]()

## Client Architecture

The SDK implements a hierarchical client architecture built on top of `httpx`.

```mermaid
graph TB
    subgraph "Client Layer"
        OpenAI["OpenAI<br/>(src/openai/_client.py)"]
        AsyncOpenAI["AsyncOpenAI<br/>(src/openai/_client.py)"]
        AzureOpenAI["AzureOpenAI<br/>(src/openai/lib/azure.py)"]
        BedrockOpenAI["BedrockOpenAI<br/>(src/openai/lib/bedrock.py)"]
        ModuleLevel["Module-Level API<br/>(src/openai/__init__.py)"]
    end
    
    subgraph "Base HTTP Layer"
        SyncAPIClient["SyncAPIClient<br/>(src/openai/_base_client.py)"]
        AsyncAPIClient["AsyncAPIClient<br/>(src/openai/_base_client.py)"]
        BaseClient["BaseClient<br/>(src/openai/_base_client.py)"]
    end
    
    subgraph "HTTP Transport"
        httpx["httpx.Client / httpx.AsyncClient"]
        httpx2["httpx2 (experimental)"]
        aiohttp["aiohttp (optional)"]
    end
    
    OpenAI --> SyncAPIClient
    AsyncOpenAI --> AsyncAPIClient
    AzureOpenAI --> SyncAPIClient
    BedrockOpenAI --> SyncAPIClient
    ModuleLevel -.lazy instantiation.-> OpenAI
    
    SyncAPIClient --> BaseClient
    AsyncAPIClient --> BaseClient
    
    SyncAPIClient --> httpx
    AsyncAPIClient --> httpx
    AsyncAPIClient -.optional.-> aiohttp
    
    BaseClient -.defines.-> RetryLogic["Retry Logic<br/>Exponential Backoff"]
    BaseClient -.defines.-> ErrorHandling["Error Handling<br/>APIError subclasses"]
```

**Key Classes:**

*   **`BaseClient`**: Foundation class providing HTTP request infrastructure, retry logic, and response parsing. [src/openai/_base_client.py:643-718]()
*   **`OpenAI` / `AsyncOpenAI`**: Main client classes exposing all API resources (e.g., `chat`, `images`, `audio`) as properties. [src/openai/_client.py:106-258]()
*   **`AzureOpenAI`**: Specialized client for Microsoft Azure OpenAI services, handling deployment-based URL mapping. [src/openai/lib/azure.py:101-200]()
*   **`BedrockOpenAI`**: Specialized client for Amazon Bedrock integration. [src/openai/lib/bedrock.py:114-175]()

The module-level API (e.g., `openai.chat.completions.create()`) provides a convenience layer that lazily instantiates an `OpenAI` client from environment variables on first use via `_ModuleClient`. [src/openai/__init__.py:176-243]()

**Sources:** [pyproject.toml:11-20](), [src/openai/_base_client.py:643-718](), [src/openai/_client.py:106-258](), [src/openai/__init__.py:176-243]()

## API Resource Organization

API resources are organized hierarchically and accessible as properties on the client:

```mermaid
graph LR
    Client["client: OpenAI"]
    
    subgraph "Primary APIs"
        responses["responses<br/>(src/openai/resources/responses/)"]
        chat["chat<br/>(src/openai/resources/chat/)"]
        beta["beta<br/>(src/openai/resources/beta/)"]
    end
    
    subgraph "Chat Sub-Resources"
        chat_completions["completions<br/>(src/openai/resources/chat/completions/)"]
    end
    
    subgraph "Beta Sub-Resources"
        assistants["assistants<br/>(src/openai/resources/beta/assistants/)"]
        realtime["realtime<br/>(src/openai/resources/beta/realtime/)"]
    end
    
    subgraph "Supporting APIs"
        embeddings["embeddings"]
        files["files"]
        images["images"]
        models["models"]
    end
    
    Client --> responses
    Client --> chat
    Client --> beta
    Client --> embeddings
    Client --> files
    Client --> images
    Client --> models
    
    chat --> chat_completions
    beta --> assistants
    beta --> realtime
```

**Resource Hierarchy:**

| Resource Path | Module | Purpose |
| :--- | :--- | :--- |
| `client.responses` | `src/openai/resources/responses/` | Modern interface for model interactions (text, audio, vision). [README.md:27-45]() |
| `client.chat.completions` | `src/openai/resources/chat/completions/` | Standard chat completions API. [README.md:47-66]() |
| `client.beta.assistants` | `src/openai/resources/beta/assistants/` | Stateful AI assistants with thread management. [api.md:195-245]() |
| `client.embeddings` | `src/openai/resources/embeddings.py` | Vector representations of text. [api.md:106-117]() |
| `client.files` | `src/openai/resources/files.py` | Document management and processing. [api.md:118-135]() |

**Sources:** [README.md:27-66](), [api.md:1-173](), [src/openai/_client.py:44-90]()

## Execution Models

The SDK supports three execution patterns:

### Synchronous Execution
Uses `httpx.Client` for blocking I/O. Suitable for scripts and synchronous web frameworks. [src/openai/_client.py:106-156]()

### Asynchronous Execution
Uses `httpx.AsyncClient` or optionally `aiohttp` (via `DefaultAioHttpClient`) for non-blocking I/O. [src/openai/_client.py:225-241](), [src/openai/_base_client.py:40]()

### Module-Level API
Convenience pattern that defers client instantiation. The module stores configuration in module-level variables (e.g., `openai.api_key`) and creates an `OpenAI` client on-demand. [src/openai/__init__.py:129-243]()

**Sources:** [README.md:29-45](), [README.md:218-241](), [src/openai/__init__.py:129-243]()

## Type System Architecture

The SDK uses a dual-layer type system for safety and validation:

1.  **Request Parameter Types**: `TypedDict` definitions (e.g., `ChatCompletionMessageParam`) for static type checking. [api.md:51-90]()
2.  **Response Model Types**: Pydantic models (inheriting from `BaseModel`) for runtime validation and attribute access. [src/openai/_models.py:76](), [src/openai/_response.py:78-80]()
3.  **Shared Types**: Common enums and models (e.g., `ChatModel`, `ReasoningEffort`) used across resources. [api.md:1-24]()

**Sources:** [pyproject.toml:13-14](), [src/openai/_models.py:76](), [src/openai/types/__init__.py]()

## Key Features

### Automatic Retries
Requests failing with connection errors or specific status codes (408, 429, 5xx) are automatically retried with exponential backoff. [src/openai/_base_client.py:83-91](), [src/openai/_base_client.py:862-937]()

### Streaming Support
Server-Sent Events (SSE) are supported for real-time response generation via `Stream` and `AsyncStream`. [src/openai/_streaming.py:92]()

### Workload Identity
Supports secure authentication in cloud environments (Kubernetes, Azure, GCP) using short-lived tokens from identity providers. [README.md:74-168](), [src/openai/_client.py:13-114]()

### Bedrock and Azure Support
Includes specialized clients for Amazon Bedrock and Microsoft Azure OpenAI services, handling provider-specific authentication and endpoint mapping. [src/openai/lib/azure.py](), [src/openai/lib/bedrock.py]()

**Sources:** [src/openai/_base_client.py:862-937](), [README.md:74-168](), [src/openai/lib/bedrock.py:114-175]()

## Project Configuration and Dependencies

The project uses **Rye** for dependency management and **Hatchling** as the build backend. [pyproject.toml:61-119]()

### Core Dependencies
| Package | Version | Purpose |
| :--- | :--- | :--- |
| `httpx` | >=0.23.0, <1 | HTTP client for sync/async requests |
| `pydantic` | >=1.9.0, <3 | Data validation and serialization |
| `anyio` | >=3.5.0, <5 | Async I/O abstraction |
| `jiter` | >=0.10.0, <1 | Fast JSON parsing |

**Sources:** [pyproject.toml:11-20]()

## Version and Compatibility
Current version: **2.49.0** [src/openai/_version.py:4]().
The library requires **Python 3.10+** [pyproject.toml:22]().

For detailed architecture, see [Architecture Overview](#1.1).
For project setup and release details, see [Project Configuration and Dependencies](#1.2).

---

# Page: Architecture Overview

# Architecture Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.stats.yml](.stats.yml)
- [README.md](README.md)
- [api.md](api.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_module_client.py](src/openai/_module_client.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/__init__.py](src/openai/resources/__init__.py)
- [src/openai/resources/admin/__init__.py](src/openai/resources/admin/__init__.py)
- [src/openai/resources/admin/admin.py](src/openai/resources/admin/admin.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



## Purpose and Scope

This document provides a detailed architectural overview of the OpenAI Python library, explaining how the major components interact to provide a typed, reliable interface to the OpenAI API. It covers the layered architecture from client initialization through HTTP communication to response parsing, including both synchronous and asynchronous patterns.

The library is generated from an OpenAPI specification ([.stats.yml:2]()) and supports Python 3.10+ ([README.md:6]()).

## High-Level Architecture

The OpenAI Python SDK is organized into distinct layers that provide a typed, reliable interface to the OpenAI API. The library exposes **278 configured API endpoints** (referenced in [.stats.yml:1]()) across numerous top-level resources.

**Overall System Architecture**

```mermaid
graph TB
    subgraph "External Systems"
        OPENAI_API["OpenAI API"]
    end
    
    subgraph "Core Client Library"
        BASE_CLIENT["BaseClient [src/openai/_base_client.py:361]"]
        SYNC_CLIENT["OpenAI Client [src/openai/_client.py:106]"]
        ASYNC_CLIENT["AsyncOpenAI Client [src/openai/_client.py:488]"]
        MODULE_CLIENT["_ModuleClient [src/openai/__init__.py:176]"]
    end
    
    subgraph "API Resources"
        CHAT["Chat [src/openai/resources/chat/chat.py]"]
        RESPONSES["Responses API [src/openai/resources/responses/responses.py]"]
        BETA["Beta [src/openai/resources/beta/beta.py]"]
        REALTIME["Realtime [src/openai/resources/realtime/realtime.py]"]
    end
    
    subgraph "Type System"
        TYPES["Generated Types [src/openai/types/__init__.py]"]
        BASE_MODEL["BaseModel [src/openai/_models.py:126]"]
        PARAMS["Request Param Types [src/openai/types/*_params.py]"]
    end
    
    subgraph "Utilities"
        TRANSFORM["Data Transformation [src/openai/_base_client.py:76]"]
        STREAMING["Streaming Handlers [src/openai/_streaming.py:82]"]
        COMPAT["Pydantic v1/v2 Compat [src/openai/_compat.py:1]"]
    end
    
    BASE_CLIENT --> SYNC_CLIENT
    BASE_CLIENT --> ASYNC_CLIENT
    SYNC_CLIENT --> MODULE_CLIENT
    SYNC_CLIENT --> CHAT
    SYNC_CLIENT --> RESPONSES
    SYNC_CLIENT --> BETA
    SYNC_CLIENT --> REALTIME
    
    TYPES --> BASE_MODEL
    BASE_MODEL --> PARAMS
    
    COMPAT --> BASE_MODEL
    TRANSFORM --> BASE_CLIENT
    STREAMING --> CHAT
    
    SYNC_CLIENT -.HTTP.-> OPENAI_API
    ASYNC_CLIENT -.HTTP.-> OPENAI_API
```

The library follows a layered architecture:

1.  **Core Client Library**: `BaseClient` ([src/openai/_base_client.py:361]()) provides HTTP infrastructure, specialized into `SyncAPIClient` ([src/openai/_base_client.py:820]()) and `AsyncAPIClient` ([src/openai/_base_client.py:1231]()).
2.  **API Resources**: Top-level resources representing OpenAI API endpoints (e.g., `chat`, `files`, `responses`).
3.  **Type System**: Pydantic-based models ([src/openai/_models.py:126]()) with custom extensions for serialization and validation.
4.  **Data Transformation**: Logic for property aliasing, Pydantic compatibility ([src/openai/_compat.py:1]()), and streaming event processing ([src/openai/_streaming.py:92]()).

Sources: [.stats.yml:1-5](), [src/openai/_client.py:106-802](), [src/openai/_base_client.py:361-1498]()

## Client Layer

The client layer provides three primary entry points for users, all inheriting from common base classes:

```mermaid
graph TB
    User["User Application"]
    
    subgraph ClientTypes["Client Implementations"]
        OpenAI["OpenAI<br/>[src/openai/_client.py:106]"]
        AsyncOpenAI["AsyncOpenAI<br/>[src/openai/_client.py:488]"]
        AzureOpenAI["AzureOpenAI<br/>[src/openai/lib/azure.py:101]"]
    end
    
    subgraph BaseClasses["Base Classes"]
        SyncAPIClient["SyncAPIClient<br/>[src/openai/_base_client.py:820]"]
        AsyncAPIClient["AsyncAPIClient<br/>[src/openai/_base_client.py:1231]"]
        BaseClient["BaseClient<br/>[src/openai/_base_client.py:361]"]
    end
    
    User --> OpenAI
    User --> AsyncOpenAI
    User --> AzureOpenAI
    
    OpenAI --> SyncAPIClient
    AsyncOpenAI --> AsyncAPIClient
    AzureOpenAI --> SyncAPIClient
    
    SyncAPIClient --> BaseClient
    AsyncAPIClient --> BaseClient
```

### Synchronous Client: `OpenAI`

The `OpenAI` class ([src/openai/_client.py:106-485]()) is the primary synchronous client.

| Feature | Implementation | Location |
| :--- | :--- | :--- |
| API Authentication | `api_key` property / `WorkloadIdentity` | [src/openai/_client.py:108, 110]() |
| Resource Access | Cached properties for each API resource | [src/openai/_client.py:375-451]() |
| Workload Identity | Short-lived token provider support | [src/openai/_client.py:131, 174]() |
| Environment Inference | `OPENAI_API_KEY`, `OPENAI_ORG_ID`, etc. | [src/openai/_client.py:160-164]() |

### Asynchronous Client: `AsyncOpenAI`

The `AsyncOpenAI` class ([src/openai/_client.py:488-833]()) provides the same API surface with async support:

-   Inherits from `AsyncAPIClient` ([src/openai/_base_client.py:1231]()).
-   Uses `httpx.AsyncClient` for non-blocking HTTP communication.
-   Uses `AsyncStream` ([src/openai/_streaming.py:92]()) as the default streaming class.

### Azure Integration: `AzureOpenAI`

Azure-specific clients (in `src/openai/lib/azure.py`) extend `OpenAI` or `AsyncOpenAI` to support Azure OpenAI service parameters like `api_version` and `azure_endpoint` ([src/openai/lib/azure.py:101]()). It specifically handles Azure-style deployment URL construction by prepending `/deployments/{model}` to paths like `/chat/completions` ([src/openai/lib/azure.py:75-80]()).

Sources: [src/openai/_client.py:106-833](), [src/openai/_base_client.py:820-1498](), [src/openai/lib/azure.py:64-101]()

## API Resources Layer

The library exposes top-level API resources organized as cached properties on the client.

**Resource Organization Diagram**

```mermaid
graph TB
    Client["OpenAI / AsyncOpenAI<br/>[src/openai/_client.py]"]
    
    subgraph Generation["Generation Resources"]
        Completions["completions [src/openai/resources/completions.py]"]
        Chat["chat [src/openai/resources/chat/chat.py]"]
        Responses["responses [src/openai/resources/responses/responses.py]"]
    end
    
    subgraph Data["Data Resources"]
        Files["files [src/openai/resources/files.py]"]
        Embeddings["embeddings [src/openai/resources/embeddings.py]"]
        VectorStores["vector_stores [src/openai/resources/vector_stores/vector_stores.py]"]
    end
    
    subgraph Beta["Beta Resources"]
        BetaRes["beta [src/openai/resources/beta/beta.py]"]
        Realtime["beta.realtime [src/openai/resources/beta/realtime/realtime.py]"]
    end
    
    Client --> Completions
    Client --> Chat
    Client --> Responses
    Client --> Files
    Client --> Embeddings
    Client --> VectorStores
    Client --> BetaRes
    BetaRes --> Realtime
```

Resources are accessed via `@cached_property` decorators ([src/openai/_client.py:375-451]()):

```python
@cached_property
def chat(self) -> Chat:
    from .resources.chat import Chat
    return Chat(self)
```

Each resource method transforms request parameters and delegates to the client's internal request methods ([src/openai/_base_client.py:610-632]()).

Sources: [src/openai/_client.py:375-451](), [src/openai/resources/__init__.py:1-260]()

## HTTP & Retry Layer

The HTTP layer, centered on `BaseClient`, handles communication, retries, and error mapping.

```mermaid
graph TB
    Resource["API Resource"]
    
    subgraph BaseClient["BaseClient [src/openai/_base_client.py:361]"]
        BuildRequest["_build_request() [src/openai/_base_client.py:475]"]
        RetryLoop["Retry Loop [src/openai/_base_client.py:750]"]
    end
    
    subgraph RetryLogic["Retry Logic"]
        ShouldRetry["_should_retry() [src/openai/_base_client.py:750]"]
        Backoff["Exponential Backoff"]
    end
    
    subgraph ErrorHandling["Error Handling"]
        MakeError["_make_status_error() [src/openai/_base_client.py:1016]"]
    end
    
    Resource --> BuildRequest
    BuildRequest --> RetryLoop
    RetryLoop --> ShouldRetry
    ShouldRetry --> Backoff
    RetryLoop --> MakeError
```

### Retry Strategy

The retry logic ([src/openai/_base_client.py:750-783]()) implements backoff:

-   **Base delay**: 0.5 seconds (`INITIAL_RETRY_DELAY` from [src/openai/_constants.py:87]()).
-   **Exponential backoff**: Doubling delay up to 8 seconds (`MAX_RETRY_DELAY` from [src/openai/_constants.py:85]()).
-   **Jitter**: Randomization to prevent thundering herd ([src/openai/_base_client.py:741]()).
-   **Status Codes**: Retries 408 (Timeout), 409 (Conflict), 429 (Rate Limit), and 5xx (Server Error) ([src/openai/_base_client.py:750-783]()).

### Error Hierarchy

HTTP status codes are mapped to specific exception types in `src/openai/_exceptions.py`:

-   **400**: `BadRequestError` ([src/openai/__init__.py:27]())
-   **401**: `AuthenticationError` ([src/openai/__init__.py:29]())
-   **404**: `NotFoundError` ([src/openai/__init__.py:23]())
-   **429**: `RateLimitError` ([src/openai/__init__.py:25]())
-   **500**: `InternalServerError` ([src/openai/__init__.py:30]())

All inherit from `APIStatusError` ([src/openai/_exceptions.py:95]()), which inherits from `OpenAIError` ([src/openai/_exceptions.py:94]()).

Sources: [src/openai/_base_client.py:726-783](), [src/openai/_constants.py:84-91](), [src/openai/_exceptions.py:93-99]()

## Data & Type System

The SDK uses a comprehensive type system built on Pydantic and TypedDicts.

| Component | Purpose | Location |
| :--- | :--- | :--- |
| `BaseModel` | Extended Pydantic model for response validation | [src/openai/_models.py:126]() |
| `TypedDict` | Parameter types for request methods | `src/openai/types/*_params.py` |
| `NotGiven` | Sentinel to distinguish `None` from an omitted argument | [src/openai/_types.py:133]() |
| `Omit` | Sentinel to explicitly remove a value from a request | [src/openai/_types.py:166]() |

### Data Transformation

The library uses a transformation pipeline to prepare data for the API. Key functions include:

-   `construct_type`: Coerces data into the expected response type ([src/openai/_base_client.py:76]()).
-   `transform`: Recursively applies property aliases and formatters to request bodies ([src/openai/_base_client.py:66]()).

Sources: [src/openai/_models.py:126](), [src/openai/_types.py:133-166](), [src/openai/_base_client.py:66-76]()

## Module-Level API Pattern

For convenience, the library provides a module-level API that uses a global client instance configured via lazy properties on a `_ModuleClient` class.

```mermaid
graph TB
    UserCode["openai.chat.completions.create()"]
    
    subgraph ModuleAPI["Module API [src/openai/__init__.py]"]
        ModuleClient["_ModuleClient [src/openai/__init__.py:176]"]
        GlobalVars["Global Config Vars (api_key, etc.)"]
    end
    
    subgraph ClientImpl["OpenAI Client [src/openai/_client.py:106]"]
        ChatRes["Chat Resource [src/openai/resources/chat/chat.py]"]
    end
    
    UserCode --> ModuleClient
    ModuleClient --> GlobalVars
    ModuleClient --> ChatRes
```

The module-level variables (e.g., `openai.api_key`) are used to configure the underlying client lazily. This allows usage like `openai.chat.completions.create(...)` without manual client instantiation ([src/openai/__init__.py:137-234]()).

Sources: [src/openai/__init__.py:129-234](), [src/openai/_client.py:106-485]()

## Response Wrappers

Users can access more than just the parsed model using specialized patterns:

-   **`with_raw_response`**: Returns a `LegacyAPIResponse` ([src/openai/_legacy_response.py:101]()) containing the `httpx.Response` and headers.
-   **`with_streaming_response`**: Returns an `APIResponse` ([src/openai/_response.py:78]()) where the body is not yet read, allowing for manual streaming control.

Sources: [src/openai/_base_client.py:77-81](), [src/openai/_response.py:78](), [src/openai/_legacy_response.py:101]()

---

# Page: Project Configuration and Dependencies

# Project Configuration and Dependencies

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.release-please-manifest.json](.release-please-manifest.json)
- [CHANGELOG.md](CHANGELOG.md)
- [pyproject.toml](pyproject.toml)
- [requirements-dev.lock](requirements-dev.lock)
- [requirements.lock](requirements.lock)
- [scripts/utils/validate-bedrock-wheel.py](scripts/utils/validate-bedrock-wheel.py)
- [scripts/utils/validate-httpx2-wheel.py](scripts/utils/validate-httpx2-wheel.py)
- [src/openai/_version.py](src/openai/_version.py)
- [tests/conftest.py](tests/conftest.py)
- [tests/lib/test_bedrock_auth_conformance.py](tests/lib/test_bedrock_auth_conformance.py)
- [uv.lock](uv.lock)

</details>



This document describes the project's configuration system, dependency management, build infrastructure, and development tooling. The `openai-python` library uses `pyproject.toml` as its central configuration file, Rye for dependency management, and Hatchling as its build backend. For information about the CI/CD pipeline and release automation, see [CI/CD Pipeline and Release Process](#8.4). For development environment setup instructions, see [8.1 Development Environment Setup]().

## Project Metadata and Package Structure

The library is configured as a standard Python package with metadata defined in [pyproject.toml:1-40](). Key identifiers:

- **Package name**: `openai` (published to PyPI) [pyproject.toml:2]()
- **Current version**: `2.49.0` ([pyproject.toml:3](), [src/openai/_version.py:4]())
- **License**: Apache-2.0 [pyproject.toml:6]()
- **Python support**: Python 3.10 and above ([pyproject.toml:22](), [CHANGELOG.md:9]())
- **Project homepage**: https://github.com/openai/openai-python [pyproject.toml:41]()

The package source code is located in `src/openai`, and the project includes several optional dependency groups for specialized functionality.

Project Metadata Mapping:
```mermaid
graph TB
    subgraph "Package Metadata"
        ProjectName["name: 'openai'"]
        Version["version: '2.49.0'<br/>from _version.py"]
        License["license: 'Apache-2.0'"]
        PythonVersions["requires-python: '>= 3.10'<br/>classifiers: 3.10-3.14"]
    end
    
    subgraph "Source Layout"
        SrcDir["src/openai/<br/>Package code"]
        VersionFile["src/openai/_version.py<br/>__version__ = '2.49.0'"]
    end
    
    subgraph "Distribution Artifacts"
        Wheel["Wheel (.whl)<br/>packages: ['src/openai']"]
        Sdist["Source Distribution<br/>includes: tests, examples, etc."]
    end
    
    ProjectName --> SrcDir
    Version --> VersionFile
    VersionFile --> Wheel
    VersionFile --> Sdist
    SrcDir --> Wheel
    SrcDir --> Sdist
```

**Sources**: [pyproject.toml:1-43](), [src/openai/_version.py:1-5](), [CHANGELOG.md:3-9]()

## Build System Configuration

The library uses Hatchling as its build backend with `hatch-fancy-pypi-readme` for dynamic README generation [pyproject.toml:118-119]():

Build Process Flow:
```mermaid
graph LR
    subgraph "Build Backend"
        Hatchling["hatchling==1.26.3<br/>build-backend"]
        FancyReadme["hatch-fancy-pypi-readme<br/>metadata hook"]
    end
    
    subgraph "Source Files"
        README["README.md<br/>Main documentation"]
        SourceCode["src/openai/**/*.py<br/>Package code"]
        Tests["tests/**<br/>Test suite"]
        Examples["examples/**<br/>Example code"]
    end
    
    subgraph "Build Artifacts"
        WheelArtifact["openai-2.49.0-py3-none-any.whl<br/>Contains: src/openai only"]
        SdistArtifact["openai-2.49.0.tar.gz<br/>Contains: src, tests, examples"]
    end
    
    Hatchling --> WheelArtifact
    Hatchling --> SdistArtifact
    FancyReadme --> README
    README --> SdistArtifact
    SourceCode --> WheelArtifact
    SourceCode --> SdistArtifact
    Tests --> SdistArtifact
    Examples --> SdistArtifact
```

The build configuration specifies:

- **Wheel packages**: Only `src/openai` is included ([pyproject.toml:127]())
- **Source distribution includes**: All non-hidden files including tests, examples, lock files, and configuration ([pyproject.toml:129-142]())
- **Dynamic README**: The `README.md` is processed to convert relative links to absolute GitHub links ([pyproject.toml:144-153]())

**Sources**: [pyproject.toml:118-153]()

## Dependency Management with Rye

The project uses Rye for dependency management, which generates lock files to ensure reproducible builds [pyproject.toml:61-62]():

| File | Purpose | Scope |
|------|---------|-------|
| `pyproject.toml` | Declares dependency constraints | All environments |
| `requirements.lock` | Locked runtime + optional dependencies | Production + optional features |
| `requirements-dev.lock` | Locked dev dependencies | Development environment |

Rye manages the project with the `managed = true` flag ([pyproject.toml:62]()). Dependencies are resolved and locked automatically when running `rye lock` or `rye sync`.

**Sources**: [pyproject.toml:61-86](), [requirements.lock:1-126](), [requirements-dev.lock:1-262]()

## Runtime Dependencies

The core runtime dependencies provide HTTP communication, data validation, and async support:

Dependency Stack:
```mermaid
graph TB
    subgraph "HTTP Layer"
        httpx["httpx>=0.23.0, <1<br/>Default HTTP client"]
    end
    
    subgraph "Data Validation"
        pydantic["pydantic>=1.9.0, <3<br/>Model validation"]
        typingext["typing-extensions>=4.14, <5<br/>Type system backports"]
    end
    
    subgraph "Async Support"
        anyio["anyio>=3.5.0, <5<br/>Async abstraction"]
        sniffio["sniffio<br/>Async runtime detection"]
    end
    
    subgraph "Utilities"
        distro["distro>=1.7.0, <2<br/>Platform detection"]
        tqdm["tqdm > 4<br/>Progress bars"]
        jiter["jiter>=0.10.0, <1<br/>Fast JSON parsing"]
    end
    
    httpx --> anyio
    pydantic --> typingext
    anyio --> sniffio
```

**Key dependency rationale:**

- **httpx**: Provides synchronous and asynchronous HTTP client with HTTP/2 support [pyproject.toml:12]()
- **pydantic**: Powers the type system and response validation; supports both v1 and v2 ([pyproject.toml:13]())
- **anyio**: Enables compatibility with multiple async backends (asyncio, trio) [pyproject.toml:15]()
- **jiter**: Fast JSON parsing library for high-performance response processing [pyproject.toml:19]()
- **distro**: Used for platform detection in user-agent headers [pyproject.toml:16]()
- **tqdm**: Provides progress bars for long-running operations [pyproject.toml:18]()

**Sources**: [pyproject.toml:11-20]()

## Optional Dependencies

The library provides several optional dependency groups for extended functionality:

```mermaid
graph TB
    subgraph "optional-dependencies"
        aiohttp_extra["[aiohttp]<br/>Alternative HTTP backend"]
        httpx2_extra["[httpx2]<br/>Experimental HTTPX2 support"]
        realtime_extra["[realtime]<br/>WebSocket support"]
        datalib_extra["[datalib]<br/>Data processing"]
        voice_extra["[voice_helpers]<br/>Audio utilities"]
        bedrock_extra["[bedrock]<br/>Amazon Bedrock support"]
    end
    
    subgraph "aiohttp Group"
        aiohttp["aiohttp>=3.14.1"]
        httpx_aiohttp["httpx_aiohttp>=0.1.9"]
    end
    
    subgraph "httpx2 Group"
        httpx2["httpx2>=2.7.0"]
        anyio_httpx2["anyio>=4.10.0"]
    end
    
    subgraph "realtime Group"
        websockets["websockets >= 13, < 16"]
    end
    
    subgraph "datalib Group"
        numpy["numpy >= 1"]
        pandas["pandas >= 1.2.3"]
        pandas_stubs["pandas-stubs >= 1.1.0.11"]
    end
    
    subgraph "voice_helpers Group"
        sounddevice["sounddevice>=0.5.1"]
        numpy_voice["numpy>=2.0.2"]
    end

    subgraph "bedrock Group"
        botocore["botocore>=1.40.0"]
    end
    
    aiohttp_extra --> aiohttp
    aiohttp_extra --> httpx_aiohttp
    httpx2_extra --> httpx2
    realtime_extra --> websockets
    datalib_extra --> numpy
    datalib_extra --> pandas
    voice_extra --> sounddevice
    bedrock_extra --> botocore
```

**Installation examples:**

```bash
# Install with aiohttp backend support
pip install openai[aiohttp]

# Install with experimental HTTPX2 support
pip install openai[httpx2]

# Install with Realtime API support
pip install openai[realtime]

# Install with data processing utilities
pip install openai[datalib]

# Install with Amazon Bedrock support
pip install openai[bedrock]
```

**Sources**: [pyproject.toml:44-59](), [CHANGELOG.md:26]()

## Development Dependencies

Development dependencies are managed through Rye and include testing, type checking, and code quality tools:

| Category | Tools | Purpose |
|----------|-------|---------|
| **Type Checking** | `pyright==1.1.399`, `mypy==1.17` | Static type analysis with dual checkers [pyproject.toml:65-66]() |
| **Testing** | `pytest`, `pytest-asyncio`, `pytest-xdist` | Test framework with async and parallel support [pyproject.toml:68-69, 84]() |
| **HTTP Mocking** | `respx` | HTTP request/response mocking for tests [pyproject.toml:67]() |
| **Code Quality** | `ruff` | Fast linter and formatter [pyproject.toml:71]() |
| **Test Utilities** | `time-machine`, `dirty-equals`, `inline-snapshot` | Testing helpers and snapshot testing [pyproject.toml:72, 74, 77]() |
| **Build Automation** | `nox` | Task automation and multi-environment testing [pyproject.toml:73]() |
| **Cloud/Identity** | `azure-identity`, `botocore` | Testing Azure and Bedrock authentication flows [pyproject.toml:78-79]() |

**Sources**: [pyproject.toml:61-86](), [requirements-dev.lock:1-262]()

## Tool Configurations

### Ruff (Linting and Formatting)

Ruff provides fast Python linting and code formatting with opinionated defaults:

```mermaid
graph TB
    subgraph "Ruff Configuration"
        LineLength["line-length = 120"]
        TargetVersion["target-version = 'py310'"]
        Format["[tool.ruff.format]<br/>docstring-code-format = true"]
    end
    
    subgraph "Lint Rules"
        Select["select = [<br/>'I' (isort)<br/>'B' (bugbear)<br/>'F401' (unused imports)<br/>'FA102' (future annotations)<br/>'E722' (bare except)]"]
    end
    
    LineLength --> Format
    TargetVersion --> Format
```

**Configuration highlights:**
- Line length: 120 characters ([pyproject.toml:255]())
- Formats code in docstrings ([pyproject.toml:260]())
- Target version: Python 3.10 ([pyproject.toml:257]())

**Sources**: [pyproject.toml:254-275]()

### Pyright (Type Checking)

Pyright runs in strict mode with comprehensive type checking:

```python
# Configuration from pyproject.toml:168-192
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.10"
reportImplicitOverride = true

# Excluded paths
exclude = [
    "_dev",
    ".venv",
    ".nox",
    ".git",
    "examples/realtime/audio_util.py",
    "examples/realtime/push_to_talk_app.py"
]
```

**Sources**: [pyproject.toml:168-192]()

### mypy (Secondary Type Checker)

mypy provides complementary type checking with different inference rules:

```python
# Configuration from pyproject.toml:193-247
[tool.mypy]
pretty = true
strict_equality = true
check_untyped_defs = true
disallow_untyped_defs = true

# Excluded modules to avoid conflicts or known limitations
exclude = [
  'src/openai/_files.py',
  '_dev/.*.py',
  'tests/.*',
  'src/openai/_utils/_logs.py',
]
```

**Sources**: [pyproject.toml:193-247]()

### pytest (Testing Framework)

pytest is configured for async testing with parallel execution:

```python
# Configuration from pyproject.toml:155-163
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short -n auto"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
filterwarnings = ["error"]
```

**Sources**: [pyproject.toml:155-163]()

## Rye Scripts and Commands

Rye provides custom script commands for common development tasks:

Script Workflow:
```mermaid
graph TB
    subgraph "Primary Commands"
        format["rye run format<br/>Complete formatting pipeline"]
        lint["rye run lint<br/>Check code quality"]
        typecheck["rye run typecheck<br/>Run type checkers"]
    end
    
    subgraph "format Chain"
        format_ruff1["format:ruff<br/>Run ruff format"]
        format_docs["format:docs<br/>Format README and api.md"]
        fix_ruff["fix:ruff<br/>Auto-fix linting issues"]
        format_ruff2["format:ruff again"]
    end
    
    format --> format_ruff1
    format_ruff1 --> format_docs
    format_docs --> fix_ruff
    fix_ruff --> format_ruff2
    
    lint --> typecheck
    typecheck --> typecheck_pyright
    typecheck --> typecheck_mypy
```

**Command details:**

| Command | Description | Implementation |
|---------|-------------|----------------|
| `rye run format` | Format code and docs, fix issues | Chains `format:ruff`, `format:docs`, `fix:ruff` ([pyproject.toml:89-95]()) |
| `rye run lint` | Check linting and types | Chains `check:ruff`, `typecheck`, `check:importable` ([pyproject.toml:99-103]()) |
| `rye run typecheck` | Run both type checkers | Chains `typecheck:pyright` and `typecheck:mypy` ([pyproject.toml:109-112]()) |

**Sources**: [pyproject.toml:88-116]()

## Version Management and Release Integration

Version information is maintained in multiple synchronized locations:

- `pyproject.toml`: `version = "2.49.0"` [pyproject.toml:3]()
- `src/openai/_version.py`: `__version__ = "2.49.0"` [src/openai/_version.py:4]()
- `.release-please-manifest.json`: `".": "2.49.0"` [.release-please-manifest.json:2]()

The version string in `_version.py` includes a special comment for automation:

```python
# From src/openai/_version.py:4
__version__ = "2.49.0"  # x-release-please-version
```

This marker allows the `release-please` automation to update version numbers. The library maintains a comprehensive `CHANGELOG.md` which tracks features (like Amazon Bedrock support and HTTPX2 support), bug fixes, and required environment updates like the move to Python 3.10 ([CHANGELOG.md:1-130]()).

**Sources**: [src/openai/_version.py:1-5](), [pyproject.toml:3](), [.release-please-manifest.json:1-3](), [CHANGELOG.md:1-130]()

---

# Page: Installation and Setup

# Installation and Setup

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.release-please-manifest.json](.release-please-manifest.json)
- [CHANGELOG.md](CHANGELOG.md)
- [README.md](README.md)
- [pyproject.toml](pyproject.toml)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_version.py](src/openai/_version.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



This page covers the basic installation process for the OpenAI Python library and initial setup steps. For detailed configuration options including timeouts, retries, and custom HTTP clients, see [Client Configuration](#2.1). For Azure-specific setup, see [Azure OpenAI Configuration](#2.2).

## Installation

### Installing from PyPI

The OpenAI Python library is available on PyPI and can be installed using pip:

```bash
pip install openai
```

The library requires **Python 3.10 or higher**.

Sources: [README.md:18-22](), [pyproject.toml:22](), [CHANGELOG.md:9]()

### Optional Dependencies

The library supports optional feature sets that can be installed as needed via `project.optional-dependencies`:

| Feature Group | Installation Command | Purpose |
|---------------|---------------------|---------|
| `aiohttp` | `pip install openai[aiohttp]` | Alternative async HTTP client support [pyproject.toml:45-48]() |
| `httpx2` | `pip install openai[httpx2]` | Experimental support for HTTPX2 clients [pyproject.toml:49-53](), [CHANGELOG.md:26]() |
| `realtime` | `pip install openai[realtime]` | WebSocket support for Realtime API [pyproject.toml:54]() |
| `datalib` | `pip install openai[datalib]` | NumPy and Pandas integration for data processing [pyproject.toml:55]() |
| `voice_helpers` | `pip install openai[voice_helpers]` | Audio device and numpy support for voice [pyproject.toml:56]() |
| `bedrock` | `pip install openai[bedrock]` | Support for Amazon Bedrock [pyproject.toml:57-59]() |

Sources: [pyproject.toml:44-60](), [README.md:245-249]()

### Core Dependencies

The library relies on several key packages to handle networking, validation, and async concurrency:

**Package Dependency Graph**

```mermaid
graph TB
    ["openai"] --> ["httpx >= 0.23.0, < 1"]
    ["openai"] --> ["pydantic >= 1.9.0, < 3"]
    ["openai"] --> ["typing-extensions >= 4.14, < 5"]
    ["openai"] --> ["anyio >= 3.5.0, < 5"]
    ["openai"] --> ["distro >= 1.7.0, < 2"]
    ["openai"] --> ["sniffio"]
    ["openai"] --> ["jiter >= 0.10.0, < 1"]
    
    ["httpx"] -.provides.-> ["SyncAPIClient"]
    ["httpx"] -.provides.-> ["AsyncAPIClient"]
    
    ["pydantic"] -.validates.-> ["BaseModel"]
    
    ["anyio"] -.supports.-> ["Async Operations"]
```

Sources: [pyproject.toml:11-20]()

## Verifying Installation

### Check Installed Version

After installation, verify the library is correctly installed and check its version:

```python
import openai
print(openai.__version__)  # e.g., "2.49.0"
```

The version string is defined in `src/openai/_version.py` and is synchronized with the project metadata via `release-please`.

Sources: [src/openai/_version.py:3-4](), [pyproject.toml:3](), [.release-please-manifest.json:2]()

### Quick Installation Test

Test basic functionality with a minimal example using the `Responses` API:

```python
from openai import OpenAI

# This will initialize the client (but not make API calls yet)
client = OpenAI()
print("OpenAI client initialized successfully")
```

Sources: [README.md:30-36]()

## Basic Setup

### API Key Configuration

The library requires an OpenAI API key for authentication. The client constructor infers these from environment variables if not provided.

**Method 1: Environment Variable (Recommended)**

Set the `OPENAI_API_KEY` environment variable. The client reads this during initialization.

```bash
export OPENAI_API_KEY="your-api-key-here"
```

**Method 2: Direct Parameter**

Pass the API key directly to the `OpenAI` or `AsyncOpenAI` constructor:

```python
from openai import OpenAI

client = OpenAI(api_key="your-api-key-here")
```

**Method 3: Workload Identity (Advanced)**

For secure cloud environments (K8s, Azure, GCP), you can use `workload_identity` with short-lived tokens.

```python
from openai import OpenAI
from openai.auth import k8s_service_account_token_provider

client = OpenAI(
    workload_identity={
        "identity_provider_id": "idp-123",
        "service_account_id": "sa-456",
        "provider": k8s_service_account_token_provider("/var/run/secrets/tokens"),
    }
)
```

Sources: [src/openai/_client.py:127-156](), [README.md:74-95]()

### Client Initialization

The library provides specialized clients for different execution models and providers:

**Client Entity Mapping**

```mermaid
graph TD
    subgraph "Natural Language Space"
        ["Synchronous Operations"]
        ["Asynchronous Operations"]
        ["Azure Cloud Provider"]
        ["Amazon Bedrock Provider"]
    end

    subgraph "Code Entity Space"
        ["OpenAI (src/openai/_client.py)"]
        ["AsyncOpenAI (src/openai/_client.py)"]
        ["AzureOpenAI (src/openai/lib/azure.py)"]
        ["BedrockOpenAI (src/openai/lib/bedrock.py)"]
        
        ["SyncAPIClient (src/openai/_base_client.py)"]
        ["AsyncAPIClient (src/openai/_base_client.py)"]
    end

    ["Synchronous Operations"] --- ["OpenAI (src/openai/_client.py)"]
    ["Asynchronous Operations"] --- ["AsyncOpenAI (src/openai/_client.py)"]
    ["Azure Cloud Provider"] --- ["AzureOpenAI (src/openai/lib/azure.py)"]
    ["Amazon Bedrock Provider"] --- ["BedrockOpenAI (src/openai/lib/bedrock.py)"]

    ["OpenAI (src/openai/_client.py)"] -- inherits --> ["SyncAPIClient (src/openai/_base_client.py)"]
    ["AzureOpenAI (src/openai/lib/azure.py)"] -- inherits --> ["SyncAPIClient (src/openai/_base_client.py)"]
    ["BedrockOpenAI (src/openai/lib/bedrock.py)"] -- inherits --> ["OpenAI (src/openai/_client.py)"]
```

Sources: [src/openai/_client.py:106](), [src/openai/_client.py:286](), [src/openai/lib/azure.py:101](), [src/openai/__init__.py:83-84]()

### Environment Variables

The library recognizes several environment variables during initialization:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Primary API authentication [src/openai/_client.py:160]() |
| `OPENAI_ADMIN_KEY` | Admin API authentication [src/openai/_client.py:161]() |
| `OPENAI_ORG_ID` | Organization identifier [src/openai/_client.py:162]() |
| `OPENAI_PROJECT_ID` | Project identifier [src/openai/_client.py:163]() |
| `AZURE_OPENAI_ENDPOINT` | Azure-specific endpoint [src/openai/__init__.py:165]() |

Sources: [src/openai/_client.py:159-167](), [src/openai/__init__.py:161-168]()

## Advanced Configuration Overview

### Timeout and Retry Configuration

The default timeout is **10 minutes** [src/openai/_constants.py:84]() and the default maximum retries is **2** [src/openai/_constants.py:86]().

```python
from openai import OpenAI

client = OpenAI(
    timeout=20.0,
    max_retries=5
)
```

For details, see [Client Configuration](#2.1).

### Module-Level API Usage

For convenience, the library supports a module-level API using a global client proxy `_ModuleClient`.

```python
import openai

openai.api_key = "..."
response = openai.chat.completions.create(model="gpt-5.5", messages=[...])
```

For details, see [Module-Level API Usage](#2.3).

Sources: [src/openai/__init__.py:176-240](), [src/openai/lib/_old_api.py:1-20]()

---

# Page: Client Configuration

# Client Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_constants.py](src/openai/_constants.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



## Purpose and Scope

This page explains how to configure the `OpenAI` and `AsyncOpenAI` client classes with authentication credentials, network settings, retry behavior, timeouts, and custom HTTP clients. This covers the core configuration options available when instantiating these clients.

For Azure-specific configuration, see [Azure OpenAI Configuration](#2.2). For information about the module-level API pattern (e.g., `openai.chat.completions`), see [Module-Level API Usage](#2.3). For detailed documentation of the client classes themselves and their resource access patterns, see [OpenAI and AsyncOpenAI Clients](#3.1).

## Configuration Overview

The client accepts configuration through three primary mechanisms:

1.  **Constructor arguments** - Explicit parameters passed during instantiation [src/openai/_client.py:126-156]().
2.  **Environment variables** - Automatic fallback when arguments are not provided [src/openai/_client.py:159-165]().
3.  **Runtime modification** - Using `copy()` or `with_options()` to create modified client instances [src/openai/_client.py:341-398]().

**Diagram: Configuration Resolution**

Title: Configuration Data Flow
```mermaid
graph LR
    subgraph "ConfigurationSources"
        ARG["Constructor Arguments"]
        ENV["Environment Variables"]
        DEFAULTS["Library Defaults"]
    end
    
    subgraph "ClientInstance"
        CLIENT["OpenAI / AsyncOpenAI"]
    end
    
    subgraph "ConfigurationEntities"
        APIKEY["api_key"]
        ORG["organization"]
        PROJ["project"]
        BASE["base_url"]
        TIMEOUT["timeout"]
        RETRIES["max_retries"]
        HEADERS["default_headers"]
        HTTP["http_client"]
    end
    
    ARG -->|"1. Priority"| CLIENT
    ENV -->|"2. Fallback"| CLIENT
    DEFAULTS -->|"3. Fallback"| CLIENT
    
    CLIENT --> APIKEY
    CLIENT --> ORG
    CLIENT --> PROJ
    CLIENT --> BASE
    CLIENT --> TIMEOUT
    CLIENT --> RETRIES
    CLIENT --> HEADERS
    CLIENT --> HTTP
```
Sources: [src/openai/_client.py:106-167](), [README.md:30-36]()

## Basic Client Instantiation

### Synchronous Client

The `OpenAI` class provides synchronous HTTP operations [src/openai/_client.py:106]().

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-...",  # Optional - defaults to OPENAI_API_KEY env var
    organization="org-...",  # Optional - defaults to OPENAI_ORG_ID env var
    project="proj_...",  # Optional - defaults to OPENAI_PROJECT_ID env var
)
```

### Asynchronous Client

The `AsyncOpenAI` class provides asynchronous HTTP operations [src/openai/_client.py:451]().

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key="sk-...",
    organization="org-...",
    project="proj_...",
)
```

Both clients share identical configuration interfaces. The synchronous client inherits from `SyncAPIClient` while the asynchronous variant inherits from `AsyncAPIClient` [src/openai/_client.py:106](), [src/openai/_client.py:451]().

Sources: [src/openai/_client.py:106-167](), [src/openai/_client.py:451-526](), [README.md:30-45](), [README.md:223-241]()

## Authentication Configuration

### API Key and Workload Identity

The SDK supports standard API keys and Workload Identity for automated environments [README.md:74-76](). API keys can be passed as strings or as a `Callable[[], str]` for dynamic retrieval [src/openai/_client.py:129]().

| Method | Source | Code Entity |
| :--- | :--- | :--- |
| **Standard API Key** | `OPENAI_API_KEY` | `self.api_key` [src/openai/_client.py:108]() |
| **Admin API Key** | `OPENAI_ADMIN_KEY` | `self.admin_api_key` [src/openai/_client.py:109]() |
| **Workload Identity** | `workload_identity` arg | `self.workload_identity` [src/openai/_client.py:110]() |

**Diagram: Authentication Logic Flow**

Title: Authentication Entity Mapping
```mermaid
graph TD
    INIT["OpenAI.__init__"]
    CHECK_WIF{"workload_identity<br/>provided?"}
    CHECK_ARG{"api_key argument<br/>provided?"}
    CHECK_CALLABLE{"Is api_key<br/>Callable?"}
    CHECK_ENV{"OPENAI_API_KEY<br/>env var set?"}
    
    WIF_AUTH["Set api_key = 'workload-identity-auth'<br/>Init WorkloadIdentityAuth"]
    STORE_STRING["Store as self.api_key"]
    STORE_CALLABLE["Store as self._api_key_provider"]
    STORE_ENV["Read from os.environ<br/>Store as self.api_key"]
    
    INIT --> CHECK_WIF
    CHECK_WIF -->|"Yes"| WIF_AUTH
    CHECK_WIF -->|"No"| CHECK_ARG
    CHECK_ARG -->|"Yes"| CHECK_CALLABLE
    CHECK_ARG -->|"No"| CHECK_ENV
    CHECK_CALLABLE -->|"Yes"| STORE_CALLABLE
    CHECK_CALLABLE -->|"No"| STORE_STRING
    CHECK_ENV -->|"Yes"| STORE_ENV
    
    WIF_AUTH --> HEADERS["auth_headers property"]
    STORE_STRING --> HEADERS
    STORE_CALLABLE --> HEADERS
    STORE_ENV --> HEADERS
```

**Workload Identity** allows using short-lived tokens from cloud providers like Kubernetes, Azure, or GCP [README.md:74-130](). It uses a `WorkloadIdentityAuth` internal handler [src/openai/_client.py:114]().

Sources: [src/openai/_client.py:106-182](), [README.md:74-152](), [src/openai/auth/__init__.py]()

### Organization and Project IDs

Organization and project IDs are sent as headers (`OpenAI-Organization` and `OpenAI-Project`) with each request [src/openai/_client.py:332-339]().

Sources: [src/openai/_client.py:111-112](), [src/openai/_client.py:332-339]()

## Network Configuration

### Base URL and WebSocket URL

The `base_url` determines the REST API endpoint, while `websocket_base_url` targets Realtime API connections [src/openai/_client.py:118-124]().

*   **Default REST Base:** The library typically defaults to the OpenAI production API [src/openai/_client.py:136]().
*   **WebSocket Logic:** If `websocket_base_url` is missing, the SDK replaces `http` with `wss` in the standard `base_url` [src/openai/_client.py:121-124]().

Sources: [src/openai/_client.py:118-137](), [src/openai/_base_client.py:560-562]()

### Timeout Configuration

Timeouts are managed via `httpx.Timeout` [src/openai/_types.py:50](). The library default is **10 minutes** for the total timeout and **5 seconds** for connection [src/openai/_constants.py:9]().

```python
from openai import OpenAI
import httpx

client = OpenAI(
    timeout=httpx.Timeout(
        timeout=600.0,
        connect=5.0
    )
)
```

Sources: [src/openai/_constants.py:9](), [src/openai/_base_client.py:122-128]()

## Request Behavior Configuration

### Retry Configuration

The SDK implements automatic retries for specific status codes (408, 409, 429, 5xx) and connection errors [src/openai/_base_client.py:93-99]().

*   **Default Max Retries:** 2 [src/openai/_constants.py:10]().
*   **Initial Delay:** 0.5s [src/openai/_constants.py:13]().
*   **Max Delay:** 8.0s [src/openai/_constants.py:14]().

Sources: [src/openai/_constants.py:10-14](), [src/openai/_base_client.py:85-87]()

### Custom Headers and Query Parameters

Global headers and query parameters can be provided during initialization and are merged into every request [src/openai/_client.py:140-141]().

Sources: [src/openai/_client.py:140-141](), [src/openai/_base_client.py:456-465]()

## Custom HTTP Client Configuration

Advanced networking scenarios like proxies require passing an `http_client` [src/openai/_client.py:145]().

```python
import httpx
from openai import OpenAI, DefaultHttpxClient

client = OpenAI(
    http_client=DefaultHttpxClient(
        proxies="http://my-proxy:8080",
        limits=httpx.Limits(max_connections=500)
    )
)
```

The `DefaultHttpxClient` and `DefaultAsyncHttpxClient` classes provide the SDK's recommended defaults (timeouts and connection limits) while allowing overrides [src/openai/_base_client.py:558-615]().

Sources: [src/openai/_client.py:145](), [src/openai/_base_client.py:558-615](), [src/openai/_constants.py:11]()

## Per-Request Configuration Overrides

The `with_options()` method (which uses `copy()`) allows temporary configuration changes without mutating the main client [src/openai/_client.py:341]().

```python
# Create a temporary client with a short timeout for one specific call
short_timeout_client = client.with_options(timeout=1.0)
response = short_timeout_client.chat.completions.create(...)
```

Sources: [src/openai/_client.py:341-398](), [tests/test_client.py:148-175]()

## Configuration Summary Table

| Argument | Type | Env Var | Code Entity |
| :--- | :--- | :--- | :--- |
| `api_key` | `str \| Callable` | `OPENAI_API_KEY` | `OpenAI.api_key` |
| `admin_api_key` | `str` | `OPENAI_ADMIN_KEY` | `OpenAI.admin_api_key` |
| `organization` | `str` | `OPENAI_ORG_ID` | `OpenAI.organization` |
| `project` | `str` | `OPENAI_PROJECT_ID` | `OpenAI.project` |
| `base_url` | `str \| URL` | - | `BaseClient.base_url` |
| `timeout` | `float \| Timeout` | - | `BaseClient.timeout` |
| `max_retries` | `int` | - | `BaseClient.max_retries` |
| `http_client` | `httpx.Client` | - | `BaseClient._client` |

Sources: [src/openai/_client.py:127-156](), [src/openai/_base_client.py:440-490]()

---

# Page: Azure OpenAI Configuration

# Azure OpenAI Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [examples/async_demo.py](examples/async_demo.py)
- [examples/azure.py](examples/azure.py)
- [examples/azure_ad.py](examples/azure_ad.py)
- [examples/demo.py](examples/demo.py)
- [examples/streaming.py](examples/streaming.py)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/lib/_validators.py](src/openai/lib/_validators.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_required_args.py](tests/test_required_args.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



This document covers the `AzureOpenAI` and `AsyncAzureOpenAI` client classes, which provide access to OpenAI models deployed on Microsoft Azure's infrastructure. It explains the Azure-specific configuration parameters, authentication methods, and how the Azure client differs from the standard OpenAI client.

---

## Overview

The Azure OpenAI service uses a different API shape and authentication mechanism compared to the standard OpenAI API. The SDK provides dedicated `AzureOpenAI` and `AsyncAzureOpenAI` classes to handle these differences.

**Key Differences from Standard Client:**
- Uses Azure-specific endpoints with resource names and deployment IDs.
- Supports both API key and Azure Active Directory (Microsoft Entra ID) authentication.
- Requires explicit API version specification via `api_version`.
- Model names are often replaced with deployment names in the request URL path.

**Sources:** [src/openai/lib/azure.py:22-33](), [src/openai/lib/azure.py:68-80](), [src/openai/lib/azure.py:101-101]()

---

## AzureOpenAI Client Class

### Basic Usage

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_version="2023-07-01-preview",
    azure_endpoint="https://example-endpoint.openai.azure.com",
)

completion = client.chat.completions.create(
    model="deployment-name",  # Your Azure deployment name
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Client Hierarchy

```mermaid
graph TB
    subgraph "Code Entity Space"
        BaseClient["BaseClient"]
        BaseAzureClient["BaseAzureClient"]
        OpenAI["OpenAI"]
        AsyncOpenAI["AsyncOpenAI"]
        AzureOpenAI["AzureOpenAI"]
        AsyncAzureOpenAI["AsyncAzureOpenAI"]
    end

    BaseClient["src/openai/_base_client.py:BaseClient"] --> BaseAzureClient["src/openai/lib/azure.py:BaseAzureClient"]
    BaseAzureClient --> AzureOpenAI["src/openai/lib/azure.py:AzureOpenAI"]
    BaseAzureClient --> AsyncAzureOpenAI["src/openai/lib/azure.py:AsyncAzureOpenAI"]
    OpenAI["src/openai/_client.py:OpenAI"] --> AzureOpenAI
    AsyncOpenAI["src/openai/_client.py:AsyncOpenAI"] --> AsyncAzureOpenAI
```

**Diagram: Azure Client Inheritance**

The `BaseAzureClient` class overrides `_prepare_url` and `_build_request` to inject `/deployments/{model}` into the path for supported endpoints.

**Sources:** [src/openai/lib/azure.py:64-66](), [src/openai/lib/azure.py:101-101](), [src/openai/lib/azure.py:216-216]()

---

## Configuration Parameters

The `AzureOpenAI` client constructors accept specific parameters for the Azure environment:

### Azure-Specific Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `azure_endpoint` | `str` | The base URL for your Azure OpenAI resource (e.g., `https://<resource-name>.openai.azure.com`). |
| `api_version` | `str` | The Azure API version to use (e.g., `2023-07-01-preview`). |
| `azure_deployment` | `str` | A default deployment name to use if the `model` parameter is omitted in requests. |
| `azure_ad_token` | `str` | A static Azure AD token for authentication. |
| `azure_ad_token_provider` | `AzureADTokenProvider` | A callable that returns an Azure AD token, enabling dynamic token refresh. |

**Sources:** [src/openai/lib/azure.py:103-122](), [src/openai/lib/azure.py:36-37]()

---

## Authentication Methods

Azure OpenAI supports three primary authentication schemes, which are mutually exclusive. Passing more than one results in a `MutuallyExclusiveAuthError`.

### 1. API Key Authentication
Uses the `api-key` HTTP header. The key can be passed via the `api_key` parameter or the `AZURE_OPENAI_API_KEY` environment variable.

### 2. Azure AD Token
Uses the `Authorization: Bearer <token>` header. A static token is provided via `azure_ad_token`.

### 3. Azure AD Token Provider
A callable function that the client invokes to retrieve a token for each request. This is the recommended way to use Managed Identities or rotating credentials.

```python
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_endpoint="https://my-resource.openai.azure.com",
    azure_ad_token_provider=token_provider,
    api_version="2023-07-01-preview",
)
```

### Authentication Logic Flow

```mermaid
sequenceDiagram
    participant App as "User Application"
    participant Client as "AzureOpenAI (src/openai/lib/azure.py)"
    participant Provider as "AzureADTokenProvider"
    participant API as "Azure OpenAI Endpoint"

    App->>Client: "chat.completions.create(model='gpt-4')"
    alt Token Provider exists
        Client->>Provider: "Invoke callback"
        Provider-->>Client: "Return str token"
        Client->>API: "POST /deployments/gpt-4/... (Header: Authorization)"
    else API Key exists
        Client->>API: "POST /deployments/gpt-4/... (Header: api-key)"
    end
    API-->>App: "JSON Response"
```

**Diagram: Azure Authentication and Request Flow**

**Sources:** [src/openai/lib/azure.py:53-61](), [src/openai/lib/azure.py:36-37](), [examples/azure_ad.py:17-26]()

---

## URL Construction and Deployment Routing

Azure OpenAI requests typically route through a deployment-specific path. The `BaseAzureClient` automatically transforms standard OpenAI paths into Azure deployment paths.

### Deployment Path Injection
If the client is configured with an `azure_endpoint` and the request `url` matches a deployment-based feature (like `/chat/completions`), the client modifies the URL:

1. It checks if the URL is in `_deployments_endpoints`.
2. It extracts the `model` from the request data (`options.json_data`).
3. It rewrites the URL to `/deployments/{model}/{original_path}`.

**Supported Deployment Endpoints:**
- `/completions`
- `/chat/completions`
- `/embeddings`
- `/audio/transcriptions`, `/audio/translations`, `/audio/speech`
- `/images/generations`, `/images/edits`

**Sources:** [src/openai/lib/azure.py:22-33](), [src/openai/lib/azure.py:69-80]()

### URL Preparation Logic

```mermaid
graph TD
    Start["_build_request(options)"] --> IsDeployment{"URL in _deployments_endpoints?"}
    IsDeployment -- "Yes" --> HasModel{"Is 'model' in json_data?"}
    HasModel -- "Yes" --> Rewrite["url = /deployments/{model}/{url}"]
    Rewrite --> Super["super()._build_request()"]
    IsDeployment -- "No" --> Super
    HasModel -- "No" --> Super

    subgraph "Path Preparation (_prepare_url)"
        Prepare["_prepare_url(url)"] --> AzureCheck{"_azure_deployment & _azure_endpoint set?"}
        AzureCheck -- "Yes" --> NonDeployment{"URL NOT in _deployments_endpoints?"}
        NonDeployment -- "Yes" --> Merge["Prepend /openai/ to path"]
    end
```

**Diagram: Azure URL Transformation Logic**

**Sources:** [src/openai/lib/azure.py:69-98](), [tests/lib/test_azure.py:39-50]()

---

## Asynchronous Azure Client

The `AsyncAzureOpenAI` class provides the same configuration interface as the synchronous version but utilizes `httpx.AsyncClient`. It supports `AsyncAzureADTokenProvider`, which can return an `Awaitable[str]`.

```python
from openai import AsyncAzureOpenAI

client = AsyncAzureOpenAI(
    azure_endpoint="https://example.openai.azure.com",
    api_version="2023-07-01-preview"
)

async def ask():
    res = await client.chat.completions.create(
        model="my-deployment",
        messages=[{"role": "user", "content": "Hi"}]
    )
```

**Sources:** [src/openai/lib/azure.py:216-216](), [src/openai/lib/azure.py:37-37]()

---

## Advanced Configuration

### Credentials Enforcement
By default, the client ensures credentials (key or token) are present during initialization. This can be disabled using `_enforce_credentials=False` for scenarios where authentication is handled by a custom `http_client` or manual headers.

**Sources:** [src/openai/lib/azure.py:122](), [tests/lib/test_azure.py:82-91]()

### Copying and Overriding
The `copy()` and `with_options()` methods allow creating a new client instance with modified Azure settings (like `api_version`) while retaining the base configuration.

```python
new_client = client.copy(api_version="2024-02-01")
```

**Sources:** [src/openai/lib/azure.py:330-335](), [tests/lib/test_azure.py:75-79]()

---

# Page: Module-Level API Usage

# Module-Level API Usage

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/bedrock.py](examples/bedrock.py)
- [src/openai/_module_client.py](src/openai/_module_client.py)
- [src/openai/lib/bedrock.py](src/openai/lib/bedrock.py)
- [src/openai/providers/bedrock.py](src/openai/providers/bedrock.py)
- [src/openai/resources/__init__.py](src/openai/resources/__init__.py)
- [src/openai/resources/admin/__init__.py](src/openai/resources/admin/__init__.py)
- [src/openai/resources/admin/admin.py](src/openai/resources/admin/admin.py)
- [tests/lib/test_bedrock.py](tests/lib/test_bedrock.py)
- [tests/test_module_client.py](tests/test_module_client.py)

</details>



This document explains the module-level client pattern in the `openai-python` library, which allows users to configure and use the API through module-level variables rather than explicit client instantiation. This pattern supports lazy initialization and automatic API type detection (OpenAI, Azure, or Amazon Bedrock).

For information about explicit client instantiation, see [Client Configuration](2.1). For Azure-specific configuration, see [Azure OpenAI Configuration](2.2).

## Overview

The module-level API pattern provides a simplified interface where users can set configuration at the module level and access API resources directly without creating a client instance:

```python
import openai

openai.api_key = "sk-..."
response = openai.chat.completions.create(...)
```

This is an alternative to the explicit client instantiation pattern:

```python
from openai import OpenAI

client = OpenAI(api_key="sk-...")
response = client.chat.completions.create(...)
```

The module-level pattern uses lazy initialization and proxy objects to provide the same functionality while maintaining backwards compatibility with earlier library versions.

**Sources:** [src/openai/_module_client.py:1-189](), [tests/test_module_client.py:11-100]()

## Configuration Variables

The library exposes the following module-level configuration variables that users can set before making API calls. These variables are synchronized with the internal `_ModuleClient` properties.

| Variable | Type | Environment Variable | Description |
|----------|------|---------------------|-------------|
| `api_key` | `str \| None` | `OPENAI_API_KEY` | OpenAI API authentication key |
| `organization` | `str \| None` | `OPENAI_ORG_ID` | OpenAI organization ID |
| `project` | `str \| None` | `OPENAI_PROJECT_ID` | OpenAI project ID |
| `webhook_secret` | `str \| None` | `OPENAI_WEBHOOK_SECRET` | Secret for webhook verification |
| `base_url` | `str \| httpx.URL \| None` | `OPENAI_BASE_URL` | Base URL for API requests |
| `timeout` | `float \| Timeout \| None` | N/A | Request timeout configuration |
| `max_retries` | `int` | N/A | Maximum number of retry attempts |
| `default_headers` | `Mapping[str, str] \| None` | N/A | Custom headers for all requests |
| `default_query` | `Mapping[str, object] \| None` | N/A | Custom query parameters |
| `http_client` | `httpx.Client \| None` | N/A | Custom HTTP client instance |
| `api_type` | `Literal["openai", "azure", "amazon-bedrock"] \| None` | `OPENAI_API_TYPE` | API type selector |
| `api_version` | `str \| None` | `OPENAI_API_VERSION` | API version (Azure only) |
| `azure_endpoint` | `str \| None` | `AZURE_OPENAI_ENDPOINT` | Azure endpoint URL (Azure only) |
| `azure_ad_token` | `str \| None` | `AZURE_OPENAI_AD_TOKEN` | Azure AD token (Azure only) |
| `azure_ad_token_provider` | `AzureADTokenProvider \| None` | N/A | Azure AD token provider (Azure only) |
| `bedrock_token_provider` | `BedrockTokenProvider \| None` | N/A | Amazon Bedrock token provider |

**Sources:** [tests/test_module_client.py:15-35](), [tests/test_module_client.py:42-99]()

## Architecture

### Module-Level Client Pattern

The architecture bridges the gap between the static `openai` module namespace and the dynamic resource instances (like `Chat` or `Completions`).

Title: Module Level Resource Proxy Architecture
```mermaid
graph TB
    subgraph "Module Level Namespace (openai.*)"
        api_key["api_key: str | None"]
        api_type["api_type: 'openai' | 'azure' | 'amazon-bedrock'"]
        chat_attr["chat (exported ChatProxy)"]
        beta_attr["beta (exported BetaProxy)"]
        responses_attr["responses (exported ResponsesProxy)"]
    end
    
    subgraph "Lazy Proxy Layer (src/openai/_module_client.py)"
        ChatProxy["ChatProxy<br/>LazyProxy['Chat']"]
        BetaProxy["BetaProxy<br/>LazyProxy['Beta']"]
        ResponsesProxy["ResponsesProxy<br/>LazyProxy['Responses']"]
    end
    
    subgraph "Client Layer (Internal)"
        _load_client["_load_client()<br/>Factory function"]
        _ModuleClient["_ModuleClient<br/>OpenAI variant"]
        _AzureModuleClient["AzureOpenAI<br/>Azure variant"]
        _BedrockModuleClient["BedrockOpenAI<br/>Bedrock variant"]
    end
    
    subgraph "Resource Entities"
        Chat["Chat (src/openai/resources/chat/chat.py)"]
        Beta["Beta (src/openai/resources/beta/beta.py)"]
        Responses["Responses (src/openai/resources/responses/responses.py)"]
    end
    
    chat_attr --> ChatProxy
    ChatProxy -->|"__load__()"| _load_client
    _load_client -->|"creates"| _ModuleClient
    _load_client -->|"or"| _AzureModuleClient
    _load_client -->|"or"| _BedrockModuleClient
    
    _ModuleClient --> Chat
    _ModuleClient --> Beta
    _ModuleClient --> Responses
    
    ChatProxy -.->|"proxies"| Chat
    BetaProxy -.->|"proxies"| Beta
    ResponsesProxy -.->|"proxies"| Responses
```

**Sources:** [src/openai/_module_client.py:32-189](), [src/openai/resources/__init__.py:11-26](), [src/openai/resources/__init__.py:115-122]()

### Lazy Initialization Flow

Accessing a module-level resource like `openai.chat` triggers a lazy-loading sequence that detects the appropriate API environment.

Title: Module Resource Resolution Sequence
```mermaid
sequenceDiagram
    participant User as User Code
    participant Proxy as ChatProxy (src/openai/_module_client.py)
    participant Loader as _load_client()
    participant Factory as Client Factory
    participant ModClient as _ModuleClient / AzureOpenAI / BedrockOpenAI
    participant Resource as Chat Resource
    
    User->>Proxy: openai.chat.completions.create(...)
    
    Note over Proxy: First access triggers __load__()
    Proxy->>Loader: __load__()
    
    alt api_type == "azure" or Azure env vars present
        Loader->>Factory: Create AzureOpenAI
        Factory-->>Loader: Azure client
    else api_type == "amazon-bedrock"
        Loader->>Factory: Create BedrockOpenAI
        Factory-->>Loader: Bedrock client
    else Default
        Loader->>Factory: Create _ModuleClient
        Factory-->>Loader: OpenAI client
    end
    
    Loader-->>Proxy: Return client
    Proxy->>ModClient: Access .chat property
    ModClient-->>Proxy: Return Chat instance
    Proxy-->>User: Delegate completions.create()
    User->>Resource: create(...)
```

**Sources:** [src/openai/_module_client.py:36-40](), [tests/test_module_client.py:122-128](), [tests/test_module_client.py:167-178](), [tests/test_module_client.py:192-202]()

## The Lazy Proxy Pattern

Resources are not instantiated when the `openai` module is imported. Instead, the module exports instances of `LazyProxy` subclasses that wrap the resource attributes of a singleton client.

### Implementation of Proxies

Each major resource has a corresponding proxy class in `src/openai/_module_client.py`. These proxies implement the `__load__` method, which calls `_load_client()` to obtain the actual client and then selects the specific resource.

| Proxy Class | Resource Loaded | Code Citation |
|-------------|-----------------|---------------|
| `ChatProxy` | `client.chat` | [src/openai/_module_client.py:36-40]() |
| `BetaProxy` | `client.beta` | [src/openai/_module_client.py:42-46]() |
| `FilesProxy` | `client.files` | [src/openai/_module_client.py:48-52]() |
| `AudioProxy` | `client.audio` | [src/openai/_module_client.py:54-58]() |
| `AdminProxy` | `client.admin` | [src/openai/_module_client.py:60-64]() |
| `ImagesProxy` | `client.images` | [src/openai/_module_client.py:72-76]() |
| `ResponsesProxy` | `client.responses` | [src/openai/_module_client.py:120-124]() |
| `FineTuningProxy` | `client.fine_tuning` | [src/openai/_module_client.py:150-154]() |

The instances are exported as module-level attributes:
```python
chat: Chat = ChatProxy().__as_proxied__()
responses: Responses = ResponsesProxy().__as_proxied__()
# ...
```
**Sources:** [src/openai/_module_client.py:168-189]()

## API Type Detection

The library determines whether to behave as a standard OpenAI client, an Azure OpenAI client, or an Amazon Bedrock client based on the provided configuration or environment variables.

### Detection Scenarios

1.  **OpenAI Default**: If only `api_key` or `OPENAI_API_KEY` is provided, the client defaults to `_ModuleClient` ([tests/test_module_client.py:122-128]()).
2.  **Azure via Environment**: If `AZURE_OPENAI_API_KEY`, `OPENAI_API_VERSION`, and `AZURE_OPENAI_ENDPOINT` are set, the module-level client automatically switches to Azure mode ([tests/test_module_client.py:155-166]()).
3.  **Amazon Bedrock**: If `api_type` is set to `"amazon-bedrock"` or `AWS_BEARER_TOKEN_BEDROCK` is present with `AWS_REGION`, it instantiates a `BedrockOpenAI` client internally ([tests/test_module_client.py:192-202](), [tests/test_module_client.py:203-214]()).

### Ambiguity and Errors
If configuration is missing for Azure (e.g., key provided but no version), the client will raise a `ValueError` upon the first resource access ([tests/test_module_client.py:130-140]()). For Bedrock, SigV4 authentication requires a replayable request body; if the body cannot be read, an `OpenAIError` is raised ([src/openai/providers/bedrock.py:51-59]()).

## Usage Examples

### Runtime Configuration Updates
The module-level pattern allows changing configuration after the module is imported. These changes are reflected in the underlying client because the `_ModuleClient` uses properties that proxy back to the module-level globals.

```python
import openai
from httpx import URL

# Initial state
openai.base_url = "http://foo.com"
assert openai.completions._client.base_url == URL("http://foo.com")

# Update state
openai.timeout = 3
assert openai.completions._client.timeout == 3
```
**Sources:** [tests/test_module_client.py:42-60]()

### Resetting State
To clear the internal singleton client and force a reconfiguration (useful in testing or multi-tenant environments), the library uses `_reset_client()`.

```python
def reset_state() -> None:
    openai._reset_client()
    openai.api_key = None
    openai.base_url = None
    # ... resets all other module vars
```
**Sources:** [tests/test_module_client.py:15-35]()

## Resource Hierarchy

The module-level API provides access to the full depth of the SDK resource tree. For example, accessing the Admin Organization:

```python
import openai

# openai.admin (AdminProxy) -> organization (Organization)
org = openai.admin.organization.retrieve("org_123")
```

| Component | Class | File |
|-----------|-------|------|
| `openai.admin` | `Admin` | [src/openai/resources/admin/admin.py:19]() |
| `.organization` | `Organization` | [src/openai/resources/admin/admin.py:21-22]() |

**Sources:** [src/openai/resources/admin/admin.py:19-22](), [src/openai/resources/admin/__init__.py:1-33]()

---

# Page: Core Client Classes

# Core Client Classes

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_legacy_response.py](src/openai/_legacy_response.py)
- [src/openai/_response.py](src/openai/_response.py)
- [src/openai/_streaming.py](src/openai/_streaming.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_legacy_response.py](tests/test_legacy_response.py)
- [tests/test_response.py](tests/test_response.py)
- [tests/test_streaming.py](tests/test_streaming.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



This page documents the foundational client classes that handle HTTP communication, request building, and response processing in the OpenAI Python SDK. These classes provide the infrastructure for making API requests, managing connections, and exposing API resources.

For information about configuring clients with API keys and other options, see [Client Configuration](#2.1). For details about the request lifecycle and data transformation, see [Request and Response Processing](#3.3). For information about API resources exposed by clients, see [API Resources and Endpoints](#4).

---

## Client Class Hierarchy

The SDK implements a multi-tier client class hierarchy that separates HTTP infrastructure, synchronous/asynchronous execution models, and OpenAI-specific configuration.

### Client Inheritance Structure
```mermaid
graph TB
    subgraph "Foundation"
        BaseClient["BaseClient&lt;HttpxClientT, DefaultStreamT&gt;<br/>[Generic base for HTTP operations]"]
    end
    
    subgraph "Execution Layer"
        SyncAPIClient["SyncAPIClient<br/>[Synchronous HTTP execution]"]
        AsyncAPIClient["AsyncAPIClient<br/>[Asynchronous HTTP execution]"]
    end
    
    subgraph "Concrete Clients"
        OpenAI["OpenAI<br/>[OpenAI API client]"]
        AsyncOpenAI["AsyncOpenAI<br/>[Async OpenAI API client]"]
        
        AzureOpenAI["AzureOpenAI<br/>[Azure OpenAI variant]"]
        AsyncAzureOpenAI["AsyncAzureOpenAI<br/>[Async Azure variant]"]
    end
    
    BaseClient --> SyncAPIClient
    BaseClient --> AsyncAPIClient
    
    SyncAPIClient --> OpenAI
    AsyncAPIClient --> AsyncOpenAI
    
    OpenAI --> AzureOpenAI
    AsyncOpenAI --> AsyncAzureOpenAI
```
**Sources:** [src/openai/_base_client.py:363-790](), [src/openai/_base_client.py:822-1138](), [src/openai/_client.py:106-433](), [src/openai/lib/azure.py:64-244]()

### BaseClient
`BaseClient` is the primary internal generic class providing the machinery for HTTP communication. It abstracts the complexities of `httpx` and provides the framework for request preparation and response handling [src/openai/_base_client.py:363-363]().

Key responsibilities include:
- **Request Construction**: Using `_build_request` to assemble `httpx.Request` objects with correct headers, credentials, and URL normalization [src/openai/_base_client.py:465-530]().
- **Retry Mechanism**: Implementing automatic retries with exponential backoff via `_should_retry` and `_calculate_retry_timeout` [src/openai/_base_client.py:532-582]().
- **Platform Detection**: Gathering system telemetry (OS, Python version, architecture) for the `X-Stainless-OS` and `X-Stainless-Runtime` headers via `get_platform` [src/openai/_base_client.py:385-420]().

**Sources:** [src/openai/_base_client.py:363-790]()

### SyncAPIClient and AsyncAPIClient
These classes specialize the base infrastructure for specific concurrency models.

| Class | HTTP Backend | Streaming Class | Execution Model |
|-------|--------------|-----------------|-----------------|
| `SyncAPIClient` | `httpx.Client` | `Stream` | Blocking I/O |
| `AsyncAPIClient` | `httpx.AsyncClient` | `AsyncStream` | `asyncio` / Non-blocking |

For details on the differences between these variants, see [OpenAI and AsyncOpenAI Clients](#3.1).

**Sources:** [src/openai/_base_client.py:822-1138](), [src/openai/_base_client.py:1141-1433]()

---

## Resource Exposure Pattern

Clients expose OpenAI API features (like Chat, Embeddings, or Realtime) through a resource-based organization. These resources are organized as cached properties to ensure they are only instantiated when needed.

### Natural Language to Code Entity Mapping
```mermaid
graph LR
    subgraph "Natural Language Concept"
        ChatConcept["'Chat with a model'"]
        FileConcept["'Upload training data'"]
        RealtimeConcept["'Low-latency voice/text'"]
    end

    subgraph "Code Entity (OpenAI Client)"
        ChatProp["client.chat"]
        FileProp["client.files"]
        RealtimeProp["client.realtime"]
        
        ChatRes["Chat(SyncAPIResource)"]
        FileRes["Files(SyncAPIResource)"]
        RealtimeRes["Realtime(SyncAPIResource)"]
    end

    ChatConcept -.-> ChatProp
    FileConcept -.-> FileProp
    RealtimeConcept -.-> RealtimeProp
    
    ChatProp --> ChatRes
    FileProp --> FileRes
    RealtimeProp --> RealtimeRes
```
**Sources:** [src/openai/_client.py:44-90](), [src/openai/resources/realtime/realtime.py:69-136]()

---

## Core Infrastructure Components

The client relies on several specialized classes to handle specific parts of the request lifecycle:

### Request Options
The SDK uses `FinalRequestOptions` to store the processed state of a request before it is converted into an HTTP call. This includes the method, URL, processed JSON data, and custom headers [src/openai/_models.py:76-76]().

### Response Parsing
Responses are managed by `APIResponse` (sync) and `AsyncAPIResponse` (async). These classes handle:
- **Lazy Parsing**: The response is not parsed into a Pydantic model until `.parse()` is called [src/openai/_response.py:129-184]().
- **Raw Access**: Providing access to the underlying `httpx.Response` via the `http_response` property [src/openai/_response.py:57-57]().

For more details, see [Request and Response Processing](#3.3) and [Response Wrappers](#3.6).

**Sources:** [src/openai/_response.py:49-232](), [src/openai/_legacy_response.py:46-245]()

### Authentication & Workload Identity
The client handles standard API key authentication as well as advanced **Workload Identity** for cloud environments (GCP, Azure, K8s).
- **Bearer Auth**: Standard `Authorization: Bearer <key>` header processing [src/openai/_client.py:127-167]().
- **Workload Identity**: Uses `WorkloadIdentityAuth` to exchange environment tokens for short-lived OpenAI tokens [src/openai/_client.py:13-13]().

For details, see [Authentication and Workload Identity](#3.7).

---

## Client Lifecycle and Modification

### Modification via `copy()`
Clients are immutable in their configuration. To change settings (like a timeout or a header) for a specific set of calls, use the `.copy()` or `.with_options()` methods, which return a new client instance sharing the same underlying connection pool [src/openai/_client.py:106-106]().

### Connection Management
Clients act as context managers. Using `with client:` or `async with client:` ensures that the underlying `httpx` transports and connection pools are closed correctly when the block exits [src/openai/_base_client.py:883-892](), [src/openai/_base_client.py:1218-1230]().

**Sources:** [src/openai/_client.py:106-433](), [tests/test_client.py:148-182]()

---

## Child Pages

For deep dives into specific areas of the client architecture, refer to the following:

*   [OpenAI and AsyncOpenAI Clients](#3.1) — Detailed parameters and sync vs async usage.
*   [HTTP Client Foundation](#3.2) — The `BaseClient` and `httpx` abstraction.
*   [Request and Response Processing](#3.3) — The lifecycle from Python dict to HTTP and back.
*   [Error Handling and Retry Logic](#3.4) — How the SDK handles failures and backoff.
*   [Pagination](#3.5) — Iterating through list endpoints.
*   [Response Wrappers](#3.6) — Accessing headers and raw bytes.
*   [Authentication and Workload Identity](#3.7) — Cloud-native identity and token management.

**Sources:** [src/openai/_base_client.py:1-1433](), [src/openai/_client.py:1-780]()

---

# Page: OpenAI and AsyncOpenAI Clients

# OpenAI and AsyncOpenAI Clients

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_module_client.py](src/openai/_module_client.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/__init__.py](src/openai/resources/__init__.py)
- [src/openai/resources/admin/__init__.py](src/openai/resources/admin/__init__.py)
- [src/openai/resources/admin/admin.py](src/openai/resources/admin/admin.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



This document details the main client classes `OpenAI` and `AsyncOpenAI` that serve as the primary entry points for interacting with the OpenAI API. These clients handle authentication, HTTP communication, resource management, and expose all API endpoints through resource properties.

For information about the underlying HTTP client infrastructure and request/response processing, see [HTTP Client Foundation](#3.2). For details on the module-level API pattern, see [Module-Level API Usage](#2.3). For Azure-specific client variants, see [Azure OpenAI Configuration](#2.2).

## Client Class Hierarchy

The `OpenAI` and `AsyncOpenAI` clients inherit from base client classes that provide HTTP communication infrastructure. The architecture separates the abstract request handling logic from the specific sync/async I/O implementations.

### Entity Relationship Diagram

Title: Client Inheritance and Composition
```mermaid
graph TB
    BaseClient["BaseClient&lt;HttpxClientT, DefaultStreamT&gt;<br/>[src/openai/_base_client.py:361]"]
    SyncAPIClient["SyncAPIClient<br/>BaseClient&lt;httpx.Client, Stream[Any]&gt;<br/>[src/openai/_base_client.py:820]"]
    AsyncAPIClient["AsyncAPIClient<br/>BaseClient&lt;httpx.AsyncClient, AsyncStream[Any]&gt;<br/>[src/openai/_base_client.py:1298]"]
    OpenAI["OpenAI<br/>[src/openai/_client.py:106]"]
    AsyncOpenAI["AsyncOpenAI<br/>[src/openai/_client.py:457]"]
    
    BaseClient --> SyncAPIClient
    BaseClient --> AsyncAPIClient
    SyncAPIClient --> OpenAI
    AsyncAPIClient --> AsyncOpenAI
    
    BaseClient -.provides.-> HTTPInfra["_build_request()<br/>_request_retry_wrapper()<br/>_should_retry()"]
    SyncAPIClient -.provides.-> SyncFeatures["httpx.Client wrapper<br/>synchronous I/O"]
    AsyncAPIClient -.provides.-> AsyncFeatures["httpx.AsyncClient wrapper<br/>asynchronous I/O"]
    OpenAI -.provides.-> OpenAIFeatures["OpenAI authentication<br/>Resource Properties<br/>Environment variable inference"]
    AsyncOpenAI -.provides.-> AsyncOpenAIFeatures["OpenAI authentication<br/>Async Resource Properties<br/>Environment variable inference"]
```
**Sources:** [src/openai/_client.py:106-126](), [src/openai/_client.py:457-477](), [src/openai/_base_client.py:361-390](), [src/openai/_base_client.py:820-869](), [src/openai/_base_client.py:1298-1348]()

## Initialization Parameters

Both `OpenAI` and `AsyncOpenAI` accept the same initialization parameters, with one key difference in the `api_key` parameter type for refreshable credentials.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str \| Callable[[], str] \| None` (sync)<br/>`str \| Callable[[], Awaitable[str]] \| None` (async) | `None` | API key or provider function. Auto-inferred from `OPENAI_API_KEY` [src/openai/_client.py:160]() |
| `admin_api_key` | `str \| None` | `None` | Admin API key for organization management. Auto-inferred from `OPENAI_ADMIN_KEY` [src/openai/_client.py:161]() |
| `workload_identity` | `WorkloadIdentity \| None` | `None` | Configuration for OIDC token exchange (K8s, Azure, GCP) [src/openai/_client.py:110]() |
| `organization` | `str \| None` | `None` | Organization ID. Auto-inferred from `OPENAI_ORG_ID` [src/openai/_client.py:162]() |
| `project` | `str \| None` | `None` | Project ID. Auto-inferred from `OPENAI_PROJECT_ID` [src/openai/_client.py:163]() |
| `webhook_secret` | `str \| None` | `None` | Webhook secret for signature verification. Auto-inferred from `OPENAI_WEBHOOK_SECRET` [src/openai/_client.py:164]() |
| `base_url` | `str \| httpx.URL \| None` | `None` | Base URL for API requests. Defaults to `"https://api.openai.com/v1"` [src/openai/_client.py:239]() |
| `websocket_base_url` | `str \| httpx.URL \| None` | `None` | Base URL for WebSocket connections (Realtime API) [src/openai/_client.py:118]() |
| `timeout` | `float \| Timeout \| None \| NotGiven` | `not_given` | Request timeout. Defaults to 10 minutes (600s) [src/openai/_constants.py:84]() |
| `max_retries` | `int` | `2` | Maximum number of retry attempts [src/openai/_constants.py:86]() |
| `http_client` | `httpx.Client \| None` (sync)<br/>`httpx.AsyncClient \| None` (async) | `None` | Custom HTTP client instance [src/openai/_client.py:145]() |

**Sources:** [src/openai/_client.py:126-156](), [src/openai/_client.py:477-507](), [src/openai/_constants.py:83-91]()

## Workload Identity Authentication

For secure, automated environments, the SDK supports Workload Identity (OIDC token exchange). When `workload_identity` is provided, the client uses `WorkloadIdentityAuth` to exchange external subject tokens for short-lived OpenAI access tokens.

```python
from openai import OpenAI
from openai.auth import k8s_service_account_token_provider

client = OpenAI(
    workload_identity={
        "identity_provider_id": "idp-123",
        "service_account_id": "sa-456",
        "provider": k8s_service_account_token_provider("/var/run/secrets/token")
    }
)
```

If `workload_identity` is used, the client uses a placeholder `WORKLOAD_IDENTITY_API_KEY_PLACEHOLDER` ("workload-identity-auth") internally while `WorkloadIdentityAuth` handles the actual token injection in `auth_headers`.

**Sources:** [src/openai/_client.py:93](), [src/openai/_client.py:208-225](), [README.md:74-95]()

## Resource Access

Both client classes expose API resources as cached properties. This lazy instantiation pattern ensures that resource classes are only imported and initialized when needed.

Title: Client Resource Property Mapping
```mermaid
graph TB
    Client["OpenAI / AsyncOpenAI<br/>[src/openai/_client.py]"]
    
    subgraph "Primary Resources"
        Responses["responses<br/>[src/openai/resources/responses/responses.py]"]
        Chat["chat<br/>[src/openai/resources/chat/chat.py]"]
        Embeddings["embeddings<br/>[src/openai/resources/embeddings.py]"]
    end
    
    subgraph "Beta Resources"
        Beta["beta<br/>[src/openai/resources/beta/beta.py]"]
        Realtime["beta.realtime<br/>[src/openai/resources/beta/realtime/realtime.py]"]
        Assistants["beta.assistants<br/>[src/openai/resources/beta/assistants/assistants.py]"]
    end
    
    subgraph "Management & Files"
        Files["files<br/>[src/openai/resources/files.py]"]
        Admin["admin<br/>[src/openai/resources/admin/admin.py]"]
        FineTuning["fine_tuning<br/>[src/openai/resources/fine_tuning/fine_tuning.py]"]
    end
    
    Client --> Responses
    Client --> Chat
    Client --> Embeddings
    Client --> Beta
    Client --> Files
    Client --> Admin
    Client --> FineTuning
    Beta --> Realtime
    Beta --> Assistants
```

**Sources:** [src/openai/_client.py:180-298](), [src/openai/_client.py:531-649](), [src/openai/resources/beta/realtime/realtime.py:66-121]()

## Client Methods

### copy() and with_options()
The `copy()` method creates a new client instance with the same configuration, allowing for overrides. `with_options()` is a functional alias for `copy()`.

**Header and Query Merging Behavior:**
*   `default_headers`: Merges with existing headers (new values override existing keys) [src/openai/_client.py:383-387]().
*   `set_default_headers`: Completely replaces the existing `default_headers` dictionary [src/openai/_client.py:388-389]().
*   `default_query`: Merges with existing query parameters [src/openai/_client.py:392-396]().
*   `set_default_query`: Completely replaces the existing `default_query` dictionary [src/openai/_client.py:397-398]().

**Sources:** [src/openai/_client.py:342-399](), [src/openai/_client.py:693-750](), [tests/test_client.py:148-175]()

### Authentication Headers
The `auth_headers` property constructs the dictionary of headers required for authentication. It prioritizes `WorkloadIdentityAuth` if configured; otherwise, it uses the `api_key`. It also handles `organization` and `project` headers if provided.

**Sources:** [src/openai/_client.py:322-340](), [src/openai/_client.py:673-691]()

## Synchronous vs Asynchronous Clients

While the API surfaces are identical, the underlying implementations differ in their I/O handling and return types for streaming.

| Aspect | OpenAI (Sync) | AsyncOpenAI (Async) |
|--------|---------------|---------------------|
| **Base Class** | `SyncAPIClient` | `AsyncAPIClient` |
| **HTTP Backend** | `httpx.Client` | `httpx.AsyncClient` |
| **Streaming** | `Stream[Any]` | `AsyncStream[Any]` |
| **API Key Provider** | `Callable[[], str]` | `Callable[[], Awaitable[str]]` |
| **Method Calls** | Blocking | Requires `await` |
| **Context Manager** | `with client:` | `async with client:` |

**Sources:** [src/openai/_client.py:106-126](), [src/openai/_client.py:457-477](), [README.md:218-244]()

## HTTP Client Lifecycle

Both clients support context manager usage for proper resource cleanup. The `BaseClient` manages the lifecycle of the underlying `httpx` client, ensuring connections are closed correctly.

```python
# Sync cleanup
with OpenAI() as client:
    client.chat.completions.create(...)

# Async cleanup
async with AsyncOpenAI() as client:
    await client.chat.completions.create(...)
```

**Sources:** [src/openai/_base_client.py:883-892](), [src/openai/_base_client.py:1361-1372](), [tests/test_client.py:118-125]()

## Error Handling

The clients map HTTP status codes to specific exception types defined in `_exceptions.py`. `APIStatusError` serves as the base class for all non-2xx responses.

| Status Code | Exception Class |
|-------------|-----------------|
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` / `OAuthError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| 5xx | `InternalServerError` |

**Sources:** [src/openai/_exceptions.py:117-163](), [src/openai/_client.py:401-433]()

## Response Wrappers

The clients expose `.with_raw_response` and `.with_streaming_response` properties on every resource. These return a version of the resource where methods return an `APIResponse` (parsed metadata + raw body) or `LegacyAPIResponse` instead of just the parsed Pydantic model.

**Sources:** [src/openai/_client.py:301-306](), [src/openai/_client.py:652-657](), [src/openai/resources/beta/realtime/realtime.py:76-92]()

---

# Page: HTTP Client Foundation

# HTTP Client Foundation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [requirements-dev.lock](requirements-dev.lock)
- [requirements.lock](requirements.lock)
- [scripts/utils/validate-bedrock-wheel.py](scripts/utils/validate-bedrock-wheel.py)
- [scripts/utils/validate-httpx2-wheel.py](scripts/utils/validate-httpx2-wheel.py)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/conftest.py](tests/conftest.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/lib/test_bedrock_auth_conformance.py](tests/lib/test_bedrock_auth_conformance.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)
- [uv.lock](uv.lock)

</details>



## Purpose and Scope

This document describes the foundational HTTP client architecture that powers all communication with the OpenAI API. It covers the `BaseClient` class hierarchy, `httpx` integration, and the mechanics of building and sending HTTP requests. For information about error handling and retry logic, see **3.4 Error Handling and Retry Logic**. For details on request parameter transformation and response parsing, see **3.3 Request and Response Processing**.

**Sources:** [src/openai/_base_client.py:1-100]()

---

## Client Class Hierarchy

The SDK uses a three-tier class hierarchy to separate HTTP infrastructure from API-specific logic. The `BaseClient` provides the abstract mechanics, while `SyncAPIClient` and `AsyncAPIClient` implement the specific execution models using `httpx`.

### Diagram: Client Entity Mapping

This diagram maps the logical client concepts to the specific classes and files where they are defined.

```mermaid
classDiagram
    class BaseClient["BaseClient (src/openai/_base_client.py)"] {
        <<abstract>>
        +_client: HttpxClientT
        +_version: str
        +_base_url: URL
        +max_retries: int
        +timeout: Timeout
        +_build_request()
        +_prepare_url()
        +_build_headers()
    }
    
    class SyncAPIClient["SyncAPIClient (src/openai/_base_client.py)"] {
        +_client: httpx.Client
        +request() ResponseT
        +close()
    }
    
    class AsyncAPIClient["AsyncAPIClient (src/openai/_base_client.py)"] {
        +_client: httpx.AsyncClient
        +request() ResponseT
        +close()
    }
    
    class OpenAI["OpenAI (src/openai/_client.py)"] {
        +api_key: str
        +organization: str
        +chat: Chat
        +completions: Completions
    }
    
    class AsyncOpenAI["AsyncOpenAI (src/openai/_client.py)"] {
        +api_key: str
        +chat: AsyncChat
    }
    
    BaseClient <|-- SyncAPIClient
    BaseClient <|-- AsyncAPIClient
    SyncAPIClient <|-- OpenAI
    AsyncAPIClient <|-- AsyncOpenAI
```

**Sources:** [src/openai/_base_client.py:361-389](), [src/openai/_base_client.py:820-869](), [src/openai/_base_client.py:1182-1231](), [src/openai/_client.py:105-175](), [src/openai/_client.py:435-526]()

### BaseClient (Abstract Layer)

`BaseClient[_HttpxClientT, _DefaultStreamT]` is the generic foundation. It handles the state required for any OpenAI API request, including versioning and base URL management.

| Property | Type | Purpose |
|----------|------|---------|
| `_client` | `httpx.Client | httpx.AsyncClient` | The underlying httpx client instance. |
| `_base_url` | `URL` | Base URL for all requests, always enforced with a trailing slash in `__init__`. |
| `max_retries` | `int` | Maximum number of retry attempts (default: 2). |
| `timeout` | `float | Timeout | None` | Request timeout configuration. |
| `_strict_response_validation` | `bool` | Enable strict Pydantic validation of responses. |

**Sources:** [src/openai/_base_client.py:361-390](), [src/openai/_constants.py:9-11]()

### SyncAPIClient (Synchronous Layer)

`SyncAPIClient` implements synchronous HTTP operations. It manages a `httpx.Client` and provides the `request()` method which orchestrates building the request, sending it, and parsing the response.

Key characteristics:
- Uses `httpx.Client` for blocking I/O [src/openai/_base_client.py:820-825]().
- Implements context manager protocol (`__enter__`, `__exit__`) for resource cleanup [src/openai/_base_client.py:883-892]().
- Wrapped with `SyncHttpxClientWrapper` to ensure `close()` is called on object deletion [src/openai/_base_client.py:809-818]().

**Sources:** [src/openai/_base_client.py:820-893]()

### AsyncAPIClient (Asynchronous Layer)

`AsyncAPIClient` implements non-blocking HTTP operations. It mirrors the sync client but uses `httpx.AsyncClient`.

Key characteristics:
- Uses `httpx.AsyncClient` for non-blocking I/O [src/openai/_base_client.py:1182-1187]().
- Implements async context manager protocol (`__aenter__`, `__aexit__`) [src/openai/_base_client.py:1245-1254]().
- Wrapped with `AsyncHttpxClientWrapper` for automatic cleanup [src/openai/_base_client.py:1149-1160]().

**Sources:** [src/openai/_base_client.py:1182-1255]()

---

## HTTP Client Integration

The SDK integrates `httpx` through wrapper classes that enforce defaults and handle resource cleanup.

### Diagram: HTTP Client Initialization Flow

This diagram bridges the user's high-level instantiation of a client to the internal creation of `httpx` entities.

```mermaid
graph TB
    subgraph "User Interface"
        OpenAIInit["OpenAI() / AsyncOpenAI()"]
    end
    
    subgraph "Client Factory Logic"
        CheckCustom{"http_client passed?"}
        DefaultSync["DefaultHttpxClient"]
        DefaultAsync["DefaultAsyncHttpxClient"]
    end
    
    subgraph "Internal Wrappers"
        SyncWrap["SyncHttpxClientWrapper"]
        AsyncWrap["AsyncHttpxClientWrapper"]
    end
    
    OpenAIInit --> CheckCustom
    CheckCustom -->|No - Sync| DefaultSync
    CheckCustom -->|No - Async| DefaultAsync
    DefaultSync --> SyncWrap
    DefaultAsync --> AsyncWrap
    CheckCustom -->|Yes| SyncWrap
    CheckCustom -->|Yes| AsyncWrap
```

**Sources:** [src/openai/_base_client.py:789-806](), [src/openai/_base_client.py:1149-1160](), [src/openai/_client.py:126-155]()

### Default HTTP Client Configuration

When no custom `http_client` is provided, the SDK uses `DefaultHttpxClient` (sync) or `DefaultAsyncHttpxClient` (async) with the following defaults:

| Configuration | Value | Purpose |
|---------------|-------|---------|
| `timeout` | `DEFAULT_TIMEOUT` | 600s total, 5s connect [src/openai/_constants.py:9](). |
| `limits` | `DEFAULT_CONNECTION_LIMITS` | 1000 max connections, 100 keep-alive [src/openai/_constants.py:11](). |
| `follow_redirects` | `True` | Standard HTTP behavior for redirects. |

**Sources:** [src/openai/_base_client.py:789-806](), [src/openai/_constants.py:9-11]()

---

## Request Building Foundation

HTTP requests are constructed through a pipeline that transforms high-level `RequestOptions` into `httpx.Request` objects.

### Request Building Sequence

```mermaid
sequenceDiagram
    participant API as "API Resource (e.g. Chat)"
    participant Client as "SyncAPIClient/AsyncAPIClient"
    participant Base as "BaseClient"
    participant HTTPX as "httpx.Client"
    
    API->>Client: request(cast_to, options)
    Client->>Client: _prepare_options(options)
    Client->>Base: _build_request(FinalRequestOptions)
    
    Base->>Base: _prepare_url(options.url)
    Base->>Base: _build_headers(options)
    
    Note over Base: Handles Auth, Retries, and JSON/Multipart
    
    Base->>HTTPX: build_request(...)
    HTTPX-->>Base: httpx.Request
    
    Base-->>Client: httpx.Request
    Client->>HTTPX: send(request)
```

**Sources:** [src/openai/_base_client.py:941-1071](), [src/openai/_base_client.py:475-558]()

### Header Construction

The `_build_headers` method merges multiple sources in a priority order:

1.  **Fixed Headers**: `Accept: application/json` and `Content-Type: application/json` (default) [src/openai/_base_client.py:657-660]().
2.  **Authentication**: Provided by the `auth_headers` property (e.g., `Bearer` token) [src/openai/_client.py:321-344]().
3.  **Client Defaults**: `default_headers` provided during client instantiation [src/openai/_base_client.py:433]().
4.  **Request Specific**: Headers passed in the specific method call via `options.headers` [src/openai/_base_client.py:433]().
5.  **Telemetry**: Platform-specific headers (OS, Arch, Runtime) and `User-Agent` [src/openai/_base_client.py:686-700]().

**Sources:** [src/openai/_base_client.py:433-457](), [src/openai/_base_client.py:647-700]()

### URL Preparation

The `_prepare_url` method merges the relative endpoint path with the `_base_url`. If an absolute URL is provided in the options, it is used directly [src/openai/_base_client.py:459-470](). For Azure-specific logic, `BaseAzureClient` overrides this to handle deployment-based pathing [src/openai/lib/azure.py:82-97]().

**Sources:** [src/openai/_base_client.py:459-470](), [src/openai/lib/azure.py:82-97]()

### Multipart Form Data Handling

If a request includes files, the `_build_request` logic shifts from JSON to `multipart/form-data`.

1.  **JSON to Form**: If `json_data` is present alongside files, it is serialized into form fields [src/openai/_base_client.py:511-516]().
2.  **Header Modification**: The `Content-Type` header is removed to allow `httpx` to generate the correct boundary string [src/openai/_base_client.py:503-505]().
3.  **File Conversion**: Files are converted to `httpx`-compatible formats using `to_httpx_files` or `async_to_httpx_files` [src/openai/_base_client.py:501]().

**Sources:** [src/openai/_base_client.py:500-541]()

---

## Connection Management

The SDK manages HTTP connections through `httpx` connection pooling.

### Resource Cleanup Mechanisms

1.  **Context Managers**: Using `with OpenAI() as client:` ensures `client.close()` is called immediately on exit [src/openai/_base_client.py:883-892]().
2.  **Explicit Close**: The `close()` method terminates the underlying `httpx` client [src/openai/_base_client.py:873-881]().
3.  **Garbage Collection**: The `HttpxClientWrapper` classes implement `__del__` to close the client if it hasn't been closed manually [src/openai/_base_client.py:809-818]().

**Sources:** [src/openai/_base_client.py:809-818](), [src/openai/_base_client.py:873-892](), [src/openai/_base_client.py:1149-1160]()

### Connection Pooling

By default, the SDK uses a pool size of 1000 total connections and 100 keep-alive connections, as defined in `DEFAULT_CONNECTION_LIMITS`.

**Sources:** [src/openai/_constants.py:11]()

---

# Page: Request and Response Processing

# Request and Response Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Brewfile](Brewfile)
- [examples/httpx2_client.py](examples/httpx2_client.py)
- [scripts/bootstrap](scripts/bootstrap)
- [scripts/format](scripts/format)
- [scripts/lint](scripts/lint)
- [scripts/mock](scripts/mock)
- [scripts/test](scripts/test)
- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_httpx2.py](src/openai/_httpx2.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_qs.py](src/openai/_qs.py)
- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [tests/test_extract_files.py](tests/test_extract_files.py)
- [tests/test_files.py](tests/test_files.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



## Purpose and Scope

This page documents the request and response processing pipeline in the OpenAI Python SDK, covering how user-provided data is transformed, sent to the API, and how responses are parsed and validated. This includes the data transformation system, HTTP request building, and response deserialization.

For information about error handling and retry logic, see [Error Handling and Retry Logic](#3.4). For details about the underlying HTTP client architecture, see [HTTP Client Foundation](#3.2). For streaming response processing, see [Streaming and Event Handling](#7.2).

---

## Request Lifecycle Overview

The following diagram illustrates the path from a high-level resource call to the final parsed response, bridging the gap between natural language concepts and the internal code entities.

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Resource as "API Resource<br/>(e.g., chat.completions)"
    participant Transform as "transform()<br/>_utils/_transform.py"
    participant BaseClient as "BaseClient<br/>_base_client.py"
    participant HTTPX as "httpx.Client"
    participant API as "OpenAI API"

    User->>Resource: "create(model='gpt-4',<br/>messages=[...])"
    Resource->>Transform: "transform(params,<br/>ParamType)"
    
    Note over Transform: "Apply PropertyInfo<br/>metadata transformations"
    Transform->>Transform: "snake_case → camelCase"
    Transform->>Transform: "datetime → ISO8601"
    Transform->>Transform: "Path → base64"
    
    Transform-->>Resource: "Transformed params"
    Resource->>BaseClient: "request(cast_to, options)"
    
    Note over BaseClient: "_prepare_options()<br/>Hook for subclasses"
    BaseClient->>BaseClient: "_build_request(options)"
    Note over BaseClient: "Build headers,<br/>serialize JSON body,<br/>construct URL"
    
    BaseClient->>HTTPX: "client.send(request)"
    HTTPX->>API: "HTTP POST"
    API-->>HTTPX: "200 OK + JSON"
    HTTPX-->>BaseClient: "httpx.Response"
    
    Note over BaseClient: "_process_response_data()"
    BaseClient->>BaseClient: "Parse JSON"
    BaseClient->>BaseClient: "construct_type(cast_to)"
    
    BaseClient-->>Resource: "Typed Response Object"
    Resource-->>User: "ChatCompletion"
```

**Sources:** [src/openai/_utils/_transform.py:92-112](), [src/openai/_models.py:149-185]()

---

## Request Transformation Pipeline

The SDK transforms user-provided parameters through a metadata-driven pipeline before sending them to the API. This ensures that Python conventions (snake_case, native types) are automatically converted to API requirements (camelCase, ISO 8601 strings).

### Data Transformation Flow

The following diagram maps the logical transformation steps to specific functions and classes in the codebase.

```mermaid
graph TB
    UserData["User Input<br/>{account_holder_name: 'John',<br/>created_at: datetime(...)}"]
    
    Transform["transform(data, ParamType)<br/>_transform.py:92-112"]
    
    Recursive["_transform_recursive()<br/>_transform.py:154-233"]
    
    CheckType{"Type<br/>Classification"}
    
    TypedDict["TypedDict<br/>_transform_typeddict()<br/>:263-281"]
    
    KeyTransform["_maybe_transform_key()<br/>Apply alias from PropertyInfo<br/>:131-147"]
    
    ValueTransform["Recursively transform<br/>nested values"]
    
    List["List[T]<br/>Transform each item"]
    
    Union["Union[A, B]<br/>Apply all transformations"]
    
    Format["PropertyInfo format<br/>_format_data()<br/>:236-260"]
    
    BaseModel["Pydantic BaseModel<br/>model_dump()"]
    
    Output["Transformed Output<br/>{accountHolderName: 'John',<br/>createdAt: '2024-01-01T00:00:00'}"]

    UserData --> Transform
    Transform --> Recursive
    Recursive --> CheckType
    
    CheckType -->|"is TypedDict"| TypedDict
    CheckType -->|"is List/Iterable"| List
    CheckType -->|"is Union"| Union
    CheckType -->|"is BaseModel"| BaseModel
    CheckType -->|"has format metadata"| Format
    
    TypedDict --> KeyTransform
    KeyTransform --> ValueTransform
    ValueTransform --> Recursive
    
    List --> Recursive
    Union --> Recursive
    
    TypedDict --> Output
    List --> Output
    Union --> Output
    Format --> Output
    BaseModel --> Output
```

**Sources:** [src/openai/_utils/_transform.py:154-233](), [src/openai/_utils/_transform.py:263-281]()

### PropertyInfo Metadata System

The `PropertyInfo` class provides declarative transformation metadata attached to type annotations using `Annotated`.

| Field | Type | Description |
|-------|------|-------------|
| `alias` | `str \| None` | The API-side field name (e.g., `camelCase`). |
| `format` | `PropertyFormat \| None` | Specific formatting: `iso8601`, `base64`, or `custom`. |
| `format_template` | `str \| None` | Template used for `custom` formatting. |
| `discriminator` | `str \| None` | Used for resolving discriminated unions. |

**Sources:** [src/openai/_utils/_transform.py:44-76]()

### Data Type Transformations

#### String Alias Transformations
The `_maybe_transform_key()` function extracts alias metadata and transforms dictionary keys. If a `PropertyInfo` with an `alias` is found in the `Annotated` metadata, the key is replaced by that alias.

**Sources:** [src/openai/_utils/_transform.py:131-147](), [tests/test_transform.py:40-48]()

#### Format Transformations
The `_format_data()` function applies format conversions based on `PropertyInfo.format`:
*   **ISO 8601:** Converts `datetime` and `date` objects to standard strings using `parse_datetime` or `parse_date` logic [src/openai/_utils/_transform.py:236-248]().
*   **Base64:** Encodes file-like objects or `Path` objects into base64 strings [src/openai/_utils/_transform.py:250-256]().

**Sources:** [src/openai/_utils/_transform.py:236-260](), [tests/test_transform.py:190-206]()

#### Pydantic Model Serialization
When a `BaseModel` is encountered, it is serialized using `model_dump()`. The SDK handles compatibility between Pydantic v1 and v2 through the `_compat` layer, ensuring `by_alias=True` is used to match API naming conventions.

**Sources:** [src/openai/_utils/_transform.py:172-173](), [src/openai/_compat.py:138-166](), [src/openai/_models.py:149-185]()

---

## Response Processing and Parsing

Once an HTTP response is received, it is processed through the response parsing logic located primarily in the core response wrappers.

### Response Data Handling

The SDK provides a `BaseModel` that extends Pydantic's base class to add utility methods like `to_dict()` and `to_json()`. These methods default to using API names (aliases) and excluding unset fields.

| Method | Role |
|--------|------|
| `to_dict()` | Recursively generates a dictionary. Defaults to `use_api_names=True`. [src/openai/_models.py:149-185]() |
| `to_json()` | Generates a JSON string. Defaults to `use_api_names=True`. [src/openai/_models.py:187-213]() |
| `construct()` | A class method for creating models from dictionaries without full Pydantic validation, used for performance in response parsing. [src/openai/_models.py:228-251]() |

**Sources:** [src/openai/_models.py:111-251]()

### Request ID Propagation
For responses parsed into `BaseModel`, the SDK extracts the `x-request-id` header and attaches it to the model instance. The `BaseModel` class defines `_request_id` as a public property for this purpose.

**Sources:** [src/openai/_models.py:132-147]()

### Loose Type Coercion
The `construct_type` function is a critical utility for response parsing. It attempts to coerce JSON data into the expected Python type, handling:
*   Nested `BaseModel` instances.
*   Unions and Discriminated Unions.
*   Lists and Dictionaries.
*   Optional types.

**Sources:** [src/openai/_models.py:3395-3450](), [tests/test_models.py:223-237]()

---

## Request Building Utilities

### File Extraction and Multipart Requests
If the request includes files, the SDK uses `extract_files` from `_utils/_utils.py` to pull file objects out of the parameter dictionary. This function is recursive and supports various array formats.

| Array Format | Field Name Result |
|--------------|-------------------|
| `brackets` | `foo[]` |
| `indices` | `foo[0]`, `foo[1]` |
| `repeat` | `foo` |

**Sources:** [src/openai/_utils/_utils.py:41-76](), [src/openai/_utils/_utils.py:79-157]()

### Sentinel Values
To distinguish between a parameter being explicitly set to `None` versus not being provided at all, the SDK uses the `NotGiven` sentinel.
*   `NotGiven`: Indicates the user did not provide a value.
*   `Omit`: Used to explicitly remove a key (like a header) from a request.

**Sources:** [src/openai/_types.py:133-164](), [src/openai/_types.py:166-189](), [src/openai/_utils/_utils.py:160-161]()

---

# Page: Error Handling and Retry Logic

# Error Handling and Retry Logic

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_exceptions.py](src/openai/_exceptions.py)
- [src/openai/lib/_parsing/_completions.py](src/openai/lib/_parsing/_completions.py)
- [src/openai/lib/_pydantic.py](src/openai/lib/_pydantic.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/lib/streaming/chat/__init__.py](src/openai/lib/streaming/chat/__init__.py)
- [src/openai/lib/streaming/chat/_completions.py](src/openai/lib/streaming/chat/_completions.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/schema_types/query.py](tests/lib/schema_types/query.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/lib/test_pydantic.py](tests/lib/test_pydantic.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



## Purpose and Scope

This document describes the error handling and automatic retry mechanisms in the `openai-python` library. It covers the exception hierarchy, retry strategies, exponential backoff implementation, and configuration options for controlling retry behavior. For information about response processing and validation, see [Request and Response Processing](3.3). For timeout configuration, see [Client Configuration](2.1).

---

## Exception Hierarchy

The library defines a structured exception hierarchy with `OpenAIError` as the base exception for all library-specific errors. All exceptions are exported at the top level of the package.

```mermaid
graph TB
    OpenAIError["OpenAIError<br/>(base exception)"]
    APIError["APIError<br/>(API communication errors)"]
    APIConnectionError["APIConnectionError<br/>(network failures)"]
    APITimeoutError["APITimeoutError<br/>(request timeouts)"]
    APIStatusError["APIStatusError<br/>(HTTP error responses)"]
    APIResponseValidationError["APIResponseValidationError<br/>(invalid response data)"]
    
    BadRequestError["BadRequestError<br/>(400)"]
    AuthenticationError["AuthenticationError<br/>(401)"]
    PermissionDeniedError["PermissionDeniedError<br/>(403)"]
    NotFoundError["NotFoundError<br/>(404)"]
    ConflictError["ConflictError<br/>(409)"]
    UnprocessableEntityError["UnprocessableEntityError<br/>(422)"]
    RateLimitError["RateLimitError<br/>(429)"]
    InternalServerError["InternalServerError<br/>(500+)"]
    
    OpenAIError --> APIError
    APIError --> APIConnectionError
    APIError --> APITimeoutError
    APIError --> APIStatusError
    APIError --> APIResponseValidationError
    
    APIStatusError --> BadRequestError
    APIStatusError --> AuthenticationError
    APIStatusError --> PermissionDeniedError
    APIStatusError --> NotFoundError
    APIStatusError --> ConflictError
    APIStatusError --> UnprocessableEntityError
    APIStatusError --> RateLimitError
    APIStatusError --> InternalServerError
    
    ContentFilterError["ContentFilterFinishReasonError"]
    LengthError["LengthFinishReasonError"]
    WebhookError["InvalidWebhookSignatureError"]
    WebSocketClosed["WebSocketConnectionClosedError"]
    WebSocketQueueFull["WebSocketQueueFullError"]
    
    OpenAIError --> ContentFilterError
    OpenAIError --> LengthError
    OpenAIError --> WebhookError
    OpenAIError --> WebSocketClosed
    OpenAIError --> WebSocketQueueFull
```

Sources: [src/openai/_exceptions.py:36-208](), [src/openai/_base_client.py:93-99](), [src/openai/__init__.py:18-39]()

---

## Error Types and Status Code Mapping

The library maps HTTP status codes to specific exception types. `APIStatusError` is the base class for all non-2xx responses.

| Status Code | Exception Type | Description |
|------------|----------------|-------------|
| 400 | `BadRequestError` | Invalid request parameters |
| 401 | `AuthenticationError` | Missing or invalid API key |
| 403 | `PermissionDeniedError` | Insufficient permissions |
| 404 | `NotFoundError` | Resource not found |
| 409 | `ConflictError` | Resource conflict (retryable) |
| 422 | `UnprocessableEntityError` | Validation error |
| 429 | `RateLimitError` | Rate limit exceeded (retryable) |
| ≥500 | `InternalServerError` | Server error (retryable) |
| N/A | `APIConnectionError` | Network connection failure (retryable) |
| N/A | `APITimeoutError` | Request timeout (retryable) |

Sources: [src/openai/_exceptions.py:117-163]()

---

## Status Error Construction Flow

When a response returns a non-success status code, the `BaseClient` uses `_make_status_error` to instantiate the appropriate exception, attempting to parse the error body for extra context like error codes and parameters.

```mermaid
sequenceDiagram
    participant Client as "BaseClient"
    participant Build as "_make_status_error_from_response"
    participant Parse as "Error Body Parser"
    participant Factory as "_make_status_error"
    participant Exception as "APIStatusError subclasses"
    
    Client->>Build: response (httpx.Response)
    
    alt Response is closed
        Build->>Build: body = None<br/>err_msg = "Error code: {status_code}"
    else Response is readable
        Build->>Parse: response.text
        alt JSON parseable
            Parse->>Build: body = parsed JSON<br/>err_msg includes body
        else Not JSON
            Parse->>Build: body = text<br/>err_msg = text or status code
        end
    end
    
    Build->>Factory: err_msg, body, response
    Factory->>Factory: Check status_code via match-case
    Factory->>Exception: Create specific instance (e.g. RateLimitError)
    Exception-->>Client: Return exception object
```

Sources: [src/openai/_base_client.py:1012-1042](), [src/openai/_exceptions.py:67-105]()

---

## Retry Logic

### Retryable Conditions

The `_should_retry()` method determines whether a failed request should be retried based on status codes or specific headers.

```mermaid
graph TD
    Start["Request Failed"]
    CheckHeader{"x-should-retry<br/>header present?"}
    HeaderTrue["Header = 'true'"]
    HeaderFalse["Header = 'false'"]
    Check408{"Status code<br/>= 408?"}
    Check409{"Status code<br/>= 409?"}
    Check429{"Status code<br/>= 429?"}
    Check500{"Status code<br/>≥ 500?"}
    Retry["Retry Request"]
    NoRetry["Raise Error"]
    
    Start --> CheckHeader
    CheckHeader -->|Yes| HeaderTrue
    CheckHeader -->|Yes| HeaderFalse
    CheckHeader -->|No| Check408
    
    HeaderTrue --> Retry
    HeaderFalse --> NoRetry
    
    Check408 -->|Yes| Retry
    Check408 -->|No| Check409
    Check409 -->|Yes| Retry
    Check409 -->|No| Check429
    Check429 -->|Yes| Retry
    Check429 -->|No| Check500
    Check500 -->|Yes| Retry
    Check500 -->|No| NoRetry
```

**Retryable status codes:**
- **408** Request Timeout
- **409** Conflict (lock timeouts)
- **429** Rate Limit
- **≥500** Internal Server Errors

Sources: [src/openai/_base_client.py:1175-1208]()

### Exponential Backoff Strategy

The retry delay calculation implements exponential backoff with jitter to avoid thundering herd problems.

```mermaid
graph LR
    Start["Calculate Retry Timeout"]
    CheckRetryAfter{"Retry-After<br/>header present?"}
    UseRetryAfter["Use Retry-After value<br/>(if 0 < value ≤ 60)"]
    CalcExponential["Calculate exponential backoff"]
    CalcRetries["nb_retries = min(max_retries - remaining, 1000)"]
    CalcSleep["sleep_seconds = min(0.5 * 2^nb_retries, 8.0)"]
    ApplyJitter["jitter = 1 - 0.25 * random()<br/>timeout = sleep_seconds * jitter"]
    Return["Return timeout"]
    
    Start --> CheckRetryAfter
    CheckRetryAfter -->|Yes, valid| UseRetryAfter
    CheckRetryAfter -->|No or invalid| CalcExponential
    
    CalcExponential --> CalcRetries
    CalcRetries --> CalcSleep
    CalcSleep --> ApplyJitter
    
    UseRetryAfter --> Return
    ApplyJitter --> Return
```

**Backoff parameters:**
- `INITIAL_RETRY_DELAY = 0.5` seconds [src/openai/_constants.py:87]()
- `MAX_RETRY_DELAY = 8.0` seconds [src/openai/_constants.py:85]()
- Formula: `min(0.5 * 2^n, 8.0) * jitter` [src/openai/_base_client.py:1165-1168]()
- Jitter range: 75-100% of calculated delay [src/openai/_base_client.py:1170]()

Sources: [src/openai/_base_client.py:1151-1173](), [src/openai/_constants.py:83-91]()

### Retry-After Header Parsing

The library respects the `Retry-After` HTTP header and the non-standard `retry-after-ms`.

| Format | Example | Parsing Method |
|--------|---------|----------------|
| Milliseconds | `retry-after-ms: 1500` | Parse as float, divide by 1000 [src/openai/_base_client.py:1124-1127]() |
| Seconds | `retry-after: 5` | Parse as float [src/openai/_base_client.py:1130-1133]() |
| HTTP date | `retry-after: Wed, 21 Oct 2015 07:28:00 GMT` | Parse date via `email.utils.parsedate_to_datetime` [src/openai/_base_client.py:1138-1143]() |

Sources: [src/openai/_base_client.py:1117-1149]()

---

## Request Retry Loop Implementation

The retry loop is implemented in `_request` for the synchronous client and `_as_request` for the asynchronous client.

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Client as "SyncAPIClient/AsyncAPIClient"
    participant Build as "_build_request"
    participant HTTP as "httpx Client"
    participant Retry as "Retry Logic"
    participant Sleep as "Sleep/Wait"
    
    User->>Client: chat.completions.create(...)
    Client->>Build: FinalRequestOptions
    Build-->>Client: httpx.Request
    
    loop While remaining_retries > 0
        Client->>HTTP: send(request)
        
        alt Success (2xx)
            HTTP-->>Client: response
            Client-->>User: Parsed Response Model
        else Retryable error (e.g. 429)
            HTTP-->>Client: error response
            Client->>Retry: _should_retry(response)
            Retry-->>Client: True
            Client->>Retry: _calculate_retry_timeout(...)
            Retry-->>Client: timeout (seconds)
            Client->>Sleep: sleep(timeout)
            Sleep-->>Client: ready
            Client->>Build: rebuild request (increment retry count header)
        else Non-retryable error (e.g. 401)
            HTTP-->>Client: error response
            Client->>Retry: _should_retry(response)
            Retry-->>Client: False
            Client-->>User: Raise AuthenticationError
        end
    end
    
    Client-->>User: Raise final error (max retries exceeded)
```

Sources: [src/openai/_base_client.py:915-1071]() (Sync), [src/openai/_base_client.py:1300-1443]() (Async)

---

## Configuration Options

### Client-Level Configuration

Retry behavior is configured during client instantiation via the `max_retries` parameter.

```python
from openai import OpenAI

# Disable retries
client = OpenAI(max_retries=0)

# Custom retry count
client = OpenAI(max_retries=5)
```

**Default:** `DEFAULT_MAX_RETRIES = 2` [src/openai/_constants.py:86]()

Sources: [src/openai/_client.py:139](), [src/openai/_base_client.py:648-650]()

### Per-Request Configuration

Override retry settings for individual requests using `.with_options()`.

```python
client = OpenAI()

# Override for specific request
response = client.with_options(max_retries=5).chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

Sources: [src/openai/_base_client.py:779-795]()

---

## Error Context and Request IDs

`APIStatusError` exceptions include a `request_id` property extracted from the `x-request-id` header, which is essential for debugging and support.

```python
import openai

try:
    client.chat.completions.create(...)
except openai.APIStatusError as exc:
    print(f"Request ID: {exc.request_id}")
    print(f"Status code: {exc.status_code}")
```

Sources: [src/openai/_exceptions.py:93-105]()

---

## Header Tracking for Retries

The client adds specific headers to track and debug retries during request building:

| Header | Value | Purpose |
|--------|-------|---------|
| `x-stainless-retry-count` | `"0"`, `"1"`, ... | Number of retries attempted [src/openai/_base_client.py:441]() |
| `x-stainless-read-timeout` | Timeout in seconds | Effective read timeout for the attempt [src/openai/_base_client.py:443]() |

Sources: [src/openai/_base_client.py:433-456]()

---

## Specialized Parsing Errors

The SDK includes specific errors for failures during structured output parsing or streaming:

- **`LengthFinishReasonError`**: Raised when a response cannot be parsed because the model reached its `max_tokens` or token limit [src/openai/_exceptions.py:166-181]().
- **`ContentFilterFinishReasonError`**: Raised when parsing fails because the content was filtered by safety systems [src/openai/_exceptions.py:183-188]().
- **`APIResponseValidationError`**: Raised when the SDK is configured with `_strict_response_validation=True` and the API returns data that does not match the Pydantic schema [src/openai/_exceptions.py:83-91]().

Sources: [src/openai/_exceptions.py:166-191](), [src/openai/lib/_parsing/_completions.py:99-103]()

---

# Page: Pagination

# Pagination

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/pagination.py](src/openai/pagination.py)
- [src/openai/resources/admin/organization/certificates.py](src/openai/resources/admin/organization/certificates.py)
- [src/openai/resources/admin/organization/projects/certificates.py](src/openai/resources/admin/organization/projects/certificates.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



## Purpose and Scope

This document covers the pagination system in the OpenAI Python SDK, which handles API responses that return large datasets across multiple pages. The system provides both automatic iteration across all pages and manual page-by-page control. For information about streaming responses (Server-Sent Events), see [7.2](). For general request/response processing, see [3.3]().

## Overview

The OpenAI API paginates list endpoints (such as `fine_tuning.jobs.list()`, `files.list()`, etc.) to manage large result sets. The library provides a cursor-based pagination system that automatically fetches subsequent pages or allows manual control over page retrieval. Pagination is implemented through a hierarchy of base classes that API-specific page types inherit from.

The system supports both synchronous and asynchronous usage patterns with identical APIs, ensuring consistency across the library.

**Sources:** [src/openai/_base_client.py:107-108](), [src/openai/pagination.py:1-17]()

## Pagination Architecture

The pagination system bridges the gap between raw HTTP list responses and high-level Python iterators.

### Entity Mapping Diagram

This diagram associates high-level concepts with specific code entities responsible for their implementation.

Title: Pagination Entity Mapping
```mermaid
graph TB
    subgraph "Natural Language Space"
        AutoIter["'Automatic Iteration'"]
        ManualPage["'Manual Page Control'"]
        NextPageInfo["'Pagination Metadata'"]
    end

    subgraph "Code Entity Space"
        BaseSyncPage["BaseSyncPage[T]<br/>src/openai/_base_client.py"]
        BaseAsyncPage["BaseAsyncPage[T]<br/>src/openai/_base_client.py"]
        PageInfo["PageInfo<br/>src/openai/_base_client.py"]
        SyncCursorPage["SyncCursorPage<br/>src/openai/pagination.py"]
    end

    AutoIter --- BaseSyncPage
    AutoIter --- BaseAsyncPage
    ManualPage --- BaseSyncPage
    NextPageInfo --- PageInfo
    SyncCursorPage --- BaseSyncPage
```

**Sources:** [src/openai/_base_client.py:131-182](), [src/openai/pagination.py:71-102]()

### Class Hierarchy

Title: Pagination Class Hierarchy
```mermaid
graph TB
    subgraph "Base Classes"
        PageInfo["PageInfo<br/>Stores next page request info"]
        BasePage["BasePage[T]<br/>Core pagination interface"]
        BaseSyncPage["BaseSyncPage[T]<br/>Sync iteration support"]
        BaseAsyncPage["BaseAsyncPage[T]<br/>Async iteration support"]
    end
    
    subgraph "Concrete Implementations"
        SyncCursorPage["SyncCursorPage<br/>Standard Cursor"]
        SyncNextCursorPage["SyncNextCursorPage<br/>'next' Field Cursor"]
        SyncConversationCursorPage["SyncConversationCursorPage<br/>Conversation Specific"]
    end
    
    BasePage --> BaseSyncPage
    BasePage --> BaseAsyncPage
    PageInfo --> BasePage
    
    BaseSyncPage --> SyncCursorPage
    BaseSyncPage --> SyncNextCursorPage
    BaseSyncPage --> SyncConversationCursorPage
```

**Sources:** [src/openai/_base_client.py:131-243](), [src/openai/pagination.py:6-17]()

## Core Components

### PageInfo

The `PageInfo` class stores the necessary information to build the request for the next page. It can store pagination information in one of three ways:

| Field | Type | Description |
|-------|------|-------------|
| `url` | `URL \| NotGiven` | Complete URL for next page request [src/openai/_base_client.py:137-137]() |
| `params` | `Query \| NotGiven` | Query parameters to merge with existing request [src/openai/_base_client.py:138-138]() |
| `json` | `Body \| NotGiven` | JSON body data to merge with existing request [src/openai/_base_client.py:139-139]() |

Only one of these fields should be set per `PageInfo` instance. The choice depends on how the API endpoint communicates pagination information.

**Sources:** [src/openai/_base_client.py:131-180]()

### BasePage

`BasePage[_T]` is the generic base class defining the core interface for pagination. It is parameterized by `_T`, which represents the pydantic model that represents an item in the response.

**Key Methods:**

- `has_next_page() -> bool`: Checks if there is another page available by examining if items exist and if `next_page_info()` returns data. [src/openai/_base_client.py:197-201]()
- `next_page_info() -> Optional[PageInfo]`: Abstract method to get the necessary information for the next request. [src/openai/_base_client.py:203-203]()
- `_get_page_items() -> Iterable[_T]`: Internal method to extract items from the current page response. [src/openai/_base_client.py:205-206]()

**Private Attributes:**

- `_options: FinalRequestOptions`: Stores the original request options used to fetch the current page. [src/openai/_base_client.py:194-194]()
- `_model: Type[_T]`: The model type for individual items on the page. [src/openai/_base_client.py:195-195]()

**Sources:** [src/openai/_base_client.py:182-241]()

### BaseSyncPage

`BaseSyncPage[_T]` extends `BasePage[_T]` to provide synchronous iteration support and page retrieval.

**Key Methods:**

- `__iter__() -> Iterator[_T]`: Yields individual items across all pages by calling `iter_pages()` and iterating through each page's items. [src/openai/_base_client.py:261-265]()
- `iter_pages() -> Iterator[SyncPageT]`: Yields the current page, then recursively yields subsequent pages. [src/openai/_base_client.py:267-273]()
- `get_next_page() -> SyncPageT`: Uses `next_page_info()` and `_info_to_options()` to fetch the next page via the client. [src/openai/_base_client.py:275-283]()

**Sources:** [src/openai/_base_client.py:243-284]()

### BaseAsyncPage

`BaseAsyncPage[_T]` provides the asynchronous equivalent of `BaseSyncPage[_T]`.

**Key Methods:**

- `__aiter__() -> AsyncIterator[_T]`: Asynchronously yields individual items across all pages. [src/openai/_base_client.py:341-345]()
- `iter_pages() -> AsyncIterator[AsyncPageT]`: Asynchronously yields page objects. [src/openai/_base_client.py:347-353]()
- `get_next_page() -> AsyncPageT`: Asynchronously fetches the next page. [src/openai/_base_client.py:355-363]()

**Sources:** [src/openai/_base_client.py:323-364]()

## Concrete Page Implementations

The SDK defines several standard page types in `src/openai/pagination.py` to handle different API pagination styles:

| Class | Description | Next Page Logic |
|-------|-------------|-----------------|
| `SyncPage` / `AsyncPage` | For endpoints that return a single list without true pagination. | Always returns `None` for next page. [src/openai/pagination.py:27-68]() |
| `SyncCursorPage` / `AsyncCursorPage` | Standard cursor-based pagination using `after`. | Uses the `id` of the last item in `data`. [src/openai/pagination.py:71-135]() |
| `SyncConversationCursorPage` / `AsyncConversationCursorPage` | Specialized cursor page for conversations. | Uses a top-level `last_id` field. [src/openai/pagination.py:137-193]() |
| `SyncNextCursorPage` / `AsyncNextCursorPage` | Cursor page using a `next` field. | Uses a top-level `next` field. [src/openai/pagination.py:195-251]() |

**Sources:** [src/openai/pagination.py:22-251]()

## Usage Patterns

### Auto-Pagination (Automatic Iteration)

The simplest usage pattern iterates directly over a page object to automatically fetch and process all items across all pages.

Title: Auto-Pagination Sequence
```mermaid
sequenceDiagram
    participant User
    participant Iterator as "__iter__() / __aiter__()"
    participant IterPages as "iter_pages()"
    participant Client as "SyncAPIClient / AsyncAPIClient"
    
    User->>Iterator: for item in page
    Iterator->>IterPages: for page in iter_pages()
    
    loop For each page
        IterPages-->>Iterator: Yield items from current page
        Iterator-->>User: Yield each item
        
        alt has_next_page() is True
            IterPages->>Client: get_next_page()
            Client-->>IterPages: New page object
        else No next page
            IterPages-->>Iterator: Done
        end
    end
```

**Sources:** [src/openai/_base_client.py:261-273](), [src/openai/_base_client.py:341-353]()

### Manual Page Control

For granular control, users can manually manage page retrieval using `has_next_page()` and `get_next_page()`.

**Sources:** [src/openai/_base_client.py:197-201](), [src/openai/_base_client.py:275-283]()

## Implementation Details

### Building Next Page Requests

When `get_next_page()` is called, the system converts the `PageInfo` into a `FinalRequestOptions` object using `_info_to_options()`:

1. **Stripping Headers:** It calls `options._strip_raw_response_header()` to ensure that `with_raw_response` headers are not propagated to subsequent automated page fetches [src/openai/_base_client.py:214-214]().
2. **Merging Params:** If `PageInfo.params` is set, it merges them into the existing query parameters [src/openai/_base_client.py:216-218]().
3. **Handling URLs:** If `PageInfo.url` is set, it extracts parameters and updates the request URL [src/openai/_base_client.py:220-225]().
4. **Merging JSON:** If `PageInfo.json` is set, it merges the data into the JSON body (only supported for mappings) [src/openai/_base_client.py:227-238]().

**Sources:** [src/openai/_base_client.py:212-241](), [src/openai/_base_client.py:275-283]()

### Client Integration

API resources utilize the client's internal list helpers to initiate paginated requests. For example, in the Admin Certificates resource:

```python
# Example logic similar to src/openai/resources/admin/organization/certificates.py
# Uses SyncPage for non-paginated lists or SyncConversationCursorPage for cursors
return self._get_api_list(
    "/organization/certificates",
    page=SyncPage[Certificate],
    options=make_request_options(
        # ...
        security={"admin_api_key_auth": True},
    ),
    model=Certificate,
)
```

**Sources:** [src/openai/resources/admin/organization/certificates.py:16-17](), [src/openai/pagination.py:27-47]()

---

# Page: Response Wrappers

# Response Wrappers

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_legacy_response.py](src/openai/_legacy_response.py)
- [src/openai/_response.py](src/openai/_response.py)
- [src/openai/_streaming.py](src/openai/_streaming.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_legacy_response.py](tests/test_legacy_response.py)
- [tests/test_response.py](tests/test_response.py)
- [tests/test_streaming.py](tests/test_streaming.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



## Purpose and Scope

Response wrappers provide alternative return patterns for API calls, allowing access to raw HTTP response data, headers, and streaming contexts. This page documents the `.with_raw_response` and `.with_streaming_response` patterns available on all resource methods in the OpenAI Python SDK. These patterns are essential for use cases requiring metadata inspection or fine-grained control over response body consumption.

## Overview

The SDK provides two primary response wrapper patterns that modify the return behavior of API calls:

| Pattern | Return Type | Use Case |
|---------|-------------|----------|
| `.with_raw_response` | `LegacyAPIResponse` | Access response headers and raw HTTP data while eagerly reading the response body. |
| `.with_streaming_response` | `APIResponse` / `AsyncAPIResponse` | Access response headers and stream the response body incrementally using a context manager. |

Both patterns are implemented as properties on the client and all resource objects. They work by intercepting the request lifecycle to modify how the response is parsed and returned to the user.

**Sources:** [src/openai/_client.py:81-91](), [src/openai/_base_client.py:67-91]()

## Access Pattern

Response wrappers are accessed by chaining the wrapper property before the resource method call. This pattern is generated for every resource method in the SDK.

```python
# Standard call: returns parsed Pydantic model
completion = client.chat.completions.create(...)

# With raw response wrapper: returns LegacyAPIResponse
response = client.chat.completions.with_raw_response.create(...)

# With streaming response wrapper: returns APIResponse (requires context manager)
with client.chat.completions.with_streaming_response.create(...) as response:
    ...
```

The wrapper pattern is available on:
- **The top-level client:** `client.with_raw_response`, `client.with_streaming_response` [src/openai/_client.py:81-91]()
- **All resource objects:** `client.chat.with_raw_response`, `client.responses.with_streaming_response`, etc. [src/openai/resources/beta/realtime/realtime.py:76-92]()
- **Nested resources:** `client.beta.realtime.with_raw_response`, etc. [src/openai/resources/beta/realtime/realtime.py:132-148]()

**Sources:** [src/openai/resources/beta/realtime/realtime.py:75-93](), [src/openai/_client.py:81-97]()

## with_raw_response Pattern

### Basic Usage

The `.with_raw_response` pattern eagerly reads the entire response body into memory and returns a `LegacyAPIResponse` object. This object provides access to the raw `httpx.Response` while still allowing you to parse the body into the expected typed model.

```python
from openai import OpenAI

client = OpenAI()
response = client.chat.completions.with_raw_response.create(
    messages=[{"role": "user", "content": "Say this is a test"}],
    model="gpt-4o",
)

# Access raw HTTP data
print(response.headers.get('x-request-id'))
print(response.status_code)
print(response.http_response)  # Underlying httpx.Response

# Parse to get the typed model (cached after first call)
completion = response.parse()
print(completion.choices[0].message.content)
```

### LegacyAPIResponse Interface

The `LegacyAPIResponse` class is a wrapper around the raw HTTP response. It is marked as legacy because it will be replaced by `APIResponse` in a future major release. [src/openai/_legacy_response.py:47-57]()

| Property/Method | Type | Description |
|-----------------|------|-------------|
| `headers` | `httpx.Headers` | Access all response headers. [src/openai/_legacy_response.py:149-150]() |
| `status_code` | `int` | The HTTP status code (e.g., 200, 400). [src/openai/_legacy_response.py:157-158]() |
| `http_response` | `httpx.Response` | The underlying response object from the `httpx` library. [src/openai/_legacy_response.py:66-66]() |
| `parse()` | `ModelT` | Parses the response body into the SDK's Pydantic models. [src/openai/_legacy_response.py:101-147]() |
| `text` | `str` | Property returning the decoded response body. [src/openai/_legacy_response.py:178-183]() |
| `content` | `bytes` | Property returning the raw binary response body. [src/openai/_legacy_response.py:169-176]() |
| `request_id` | `str \| None` | Convenience property for the `x-request-id` header. [src/openai/_legacy_response.py:92-93]() |

**Sources:** [src/openai/_legacy_response.py:46-208]()

## with_streaming_response Pattern

### Basic Usage

The `.with_streaming_response` pattern returns an `APIResponse` (sync) or `AsyncAPIResponse` (async) object. Unlike the raw response pattern, it does **not** read the body immediately. This allows you to inspect headers and then stream the body content.

```python
from openai import OpenAI

client = OpenAI()

with client.chat.completions.with_streaming_response.create(
    messages=[{"role": "user", "content": "Say this is a test"}],
    model="gpt-4o",
) as response:
    # Access headers immediately without reading the body
    print(response.headers.get("Content-Type"))
    
    # Stream the response body line by line
    for line in response.iter_lines():
        print(line)
```

### Context Manager Requirement

A context manager (`with` or `async with`) is **mandatory**. Because the body is streamed, the connection remains open until the context block exits. The `APIResponse` classes implement `__enter__` and `__exit__` to ensure the underlying `httpx.Response` is closed correctly.

**Sources:** [src/openai/_response.py:246-261](), [src/openai/_response.py:421-435]()

### APIResponse Interface

The `APIResponse` and `AsyncAPIResponse` objects provide methods for controlled body consumption.

| Method | Sync/Async | Description |
|--------|------------|-------------|
| `read()` | Both | Reads the entire response body as bytes. [src/openai/_response.py:263-264]() |
| `text()` | Both | Reads the entire response body as a string. [src/openai/_response.py:267-268]() |
| `json()` | Both | Parses the response body as JSON. [src/openai/_response.py:271-272]() |
| `parse()` | Both | Parses the body into the typed Pydantic model. [src/openai/_response.py:129-183]() |
| `iter_bytes()` | Both | Iterates over the response body in binary chunks. [src/openai/_response.py:281-282]() |
| `iter_lines()` | Both | Iterates over the response body line by line. [src/openai/_response.py:291-292]() |

**Sources:** [src/openai/_response.py:49-311]()

## Implementation Architecture

The wrapper pattern is implemented by injecting specific internal headers into the request options before they reach the `BaseClient`.

### Wrapper Flow Diagram

The following diagram shows how a request is transformed when using a wrapper.

**Response Wrapper Request Lifecycle**

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Wrapper as "SyncAPIResource"
    participant Client as "BaseClient"
    participant HTTP as "httpx.Client"
    
    User->>Wrapper: ".with_raw_response.create(...)"
    Note over Wrapper: Injects "OVERRIDE_CAST_TO_HEADER"<br/>and "RAW_RESPONSE_HEADER"
    Wrapper->>Client: "_request(FinalRequestOptions)"
    
    Client->>Client: "_maybe_override_cast_to()"
    Note over Client: Detects wrapper header,<br/>sets "cast_to" to "LegacyAPIResponse"
    
    Client->>HTTP: "send(request)"
    HTTP-->>Client: "httpx.Response"
    
    alt "_should_stream_response_body"
        Client-->>User: "APIResponse (Lazy)"
    else "is_raw_response"
        Client->>Client: "Read body"
        Client-->>User: "LegacyAPIResponse (Eager)"
    end
```

**Sources:** [src/openai/_base_client.py:590-608](), [src/openai/_constants.py:88-89](), [src/openai/_response.py:49-71]()

### System Entity Mapping

This diagram bridges the natural language concepts to the specific code entities responsible for response wrapping.

**Code Entity Space: Response Wrappers**

```mermaid
classDiagram
    class BaseClient {
        <<abstract>>
        +"_request()"
        #"_maybe_override_cast_to()"
        #"_should_stream_response_body()"
    }
    
    class APIResponse {
        +"http_response: httpx.Response"
        +"_parse()"
        +"iter_lines()"
        +"read()"
    }
    
    class LegacyAPIResponse {
        +"http_response: httpx.Response"
        +"parse()"
        +"content: bytes"
        +"text: str"
    }

    class FinalRequestOptions {
        +"headers: dict"
    }

    BaseClient ..> APIResponse : "returns if RAW_RESPONSE_HEADER present"
    BaseClient ..> LegacyAPIResponse : "returns if OVERRIDE_CAST_TO_HEADER present"
    BaseClient ..> FinalRequestOptions : "consumes"
```

**Sources:** [src/openai/_base_client.py:590-608](), [src/openai/_response.py:49-71](), [src/openai/_legacy_response.py:46-89](), [src/openai/_constants.py:88-89]()

## Internal Mechanics

### Internal Headers
The SDK uses two sentinel headers defined in `_constants.py` to trigger wrapper behavior internally. These headers are stripped before the request is sent to OpenAI's servers.

- `X-Stainless-Raw-Response`: Triggers the return of a raw response wrapper instead of a parsed model. [src/openai/_constants.py:88-88]()
- `____stainless_override_cast_to`: Informs the `BaseClient` to ignore the default resource return type and instead use the wrapper type. [src/openai/_constants.py:89-89]()

### Conditional Parsing Logic
In `BaseClient._request`, the SDK checks `_should_stream_response_body()`. If true (which occurs when the user calls `.with_streaming_response`), it skips the automatic body reading and returns an `APIResponse` object that holds the open connection. [src/openai/_base_client.py:607-608]()

## Async Client Usage

The `AsyncOpenAI` client uses `AsyncAPIResponse`. Because this wrapper performs I/O on demand, almost all methods for consuming the body are coroutines.

```python
async with client.chat.completions.with_streaming_response.create(
    messages=[{"role": "user", "content": "Hello"}],
    model="gpt-4",
) as response:
    # Headers are available immediately
    print(response.headers.get("x-request-id"))
    
    # Body consumption must be awaited
    content = await response.read() 
    
    # Or streamed asynchronously
    async for line in response.iter_lines():
        print(line)
```

**Sources:** [src/openai/_response.py:341-360](), [tests/test_client.py:128-147]()

## Comparison Summary

| Feature | `with_raw_response` | `with_streaming_response` |
|---------|-------------------|---------------------------|
| **Return Class** | `LegacyAPIResponse` | `APIResponse` |
| **I/O Timing** | Eager (reads body during request) | Lazy (reads body on method call) |
| **Memory** | Higher (stores full body) | Lower (can process in chunks) |
| **Cleanup** | Automatic | Requires Context Manager |
| **Best For** | Header inspection, Debugging | File downloads, Large data processing |

**Sources:** [src/openai/_response.py:49-127](), [src/openai/_legacy_response.py:46-89](), [tests/test_client.py:128-147]()

---

# Page: Authentication and Workload Identity

# Authentication and Workload Identity

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/auth/_workload.py](src/openai/auth/_workload.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_auth.py](tests/test_auth.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



The OpenAI Python SDK supports several authentication mechanisms to accommodate different security requirements and environments. While traditional API Key authentication is the most common for development, the SDK provides robust support for Admin API Keys and Workload Identity for secure, automated cloud deployments using short-lived tokens.

## Authentication Schemes

The SDK primarily uses Bearer token authentication in the HTTP `Authorization` header. Depending on the client configuration, this token is either a long-lived API key or a short-lived token generated via Workload Identity.

### API Key Authentication
This is the default scheme. The SDK looks for the `OPENAI_API_KEY` environment variable or an explicit `api_key` parameter during client initialization [src/openai/_client.py:160-160](). The key is stored as a string or a callable that returns a string [src/openai/_client.py:129-129]().

### Admin API Key Authentication
For organization management tasks, the SDK supports an `admin_api_key` (environment variable `OPENAI_ADMIN_KEY`) [src/openai/_client.py:161-161](). This key is used for administrative resources such as managing organization-level settings or keys via the `client.admin` resource [src/openai/_client.py:109-109]().

### Workload Identity
Workload Identity allows applications running in cloud environments (Kubernetes, Azure, GCP) to authenticate without long-lived secrets. It uses short-lived tokens from the cloud provider's identity service to exchange for an OpenAI access token [README.md:74-77]().

## Workload Identity Implementation

Workload Identity is implemented via the `WorkloadIdentityAuth` class [src/openai/auth/_workload.py:174-174](), which manages the lifecycle of short-lived tokens, including proactive refreshing before expiration.

### Core Entities and Data Flow

The following diagram illustrates how the `WorkloadIdentityAuth` component integrates into the `OpenAI` client's request lifecycle to provide automated token exchange.

**Diagram: Workload Identity Request Flow**
```mermaid
graph TD
    subgraph "Natural Language Space"
        User["Developer"]
        CloudEnv["Cloud Provider (K8s/Azure/GCP)"]
    end

    subgraph "Code Entity Space"
        Client["OpenAI [src/openai/_client.py]"]
        Auth["WorkloadIdentityAuth [src/openai/auth/_workload.py]"]
        Provider["SubjectTokenProvider [src/openai/auth/_workload.py]"]
        BaseClient["BaseClient [src/openai/_base_client.py]"]
    end

    User -- "configures WorkloadIdentity" --> Client
    Client -- "initializes" --> Auth
    Auth -- "wraps" --> Provider
    
    BaseClient -- "_build_request()" --> Auth
    Auth -- "get_token()" --> Provider
    Provider -- "fetches Subject Token" --> CloudEnv
    Auth -- "Exchanges for Access Token" --> OAI_Auth["OpenAI Auth Service"]
    Auth -- "returns Bearer Token" --> BaseClient
    BaseClient -- "injects Authorization Header" --> HTTP["httpx.Request"]
```
Sources: [src/openai/_client.py:126-156](), [src/openai/auth/_workload.py:174-210](), [src/openai/_base_client.py:641-650]().

### Key Components

| Class/Type | Description |
| :--- | :--- |
| `WorkloadIdentity` | A `TypedDict` defining the configuration: `identity_provider_id`, `service_account_id`, and the `provider` [src/openai/auth/_workload.py:30-43](). |
| `SubjectTokenProvider` | A `TypedDict` defining how to retrieve a subject token (`get_token`) and its type (`jwt` or `id`) [src/openai/auth/_workload.py:25-28](). |
| `WorkloadIdentityAuth` | Internal class that handles the logic of calling the provider, exchanging tokens via OAuth2 token exchange, and caching the token [src/openai/auth/_workload.py:174-180](). |

## Supported Providers

The SDK includes built-in providers for common cloud environments. These functions return a `SubjectTokenProvider` structure used by the auth manager.

### Kubernetes
Uses service account tokens typically mounted by the K8s API server.
*   **Function**: `k8s_service_account_token_provider(token_file_path)` [src/openai/auth/_workload.py:45-47]().
*   **Default Path**: `/var/run/secrets/kubernetes.io/serviceaccount/token` [src/openai/auth/_workload.py:46-46]().

### Azure Managed Identity
Fetches tokens from the Azure Instance Metadata Service (IMDS) endpoint `169.254.169.254`.
*   **Function**: `azure_managed_identity_token_provider(resource, ...)` [src/openai/auth/_workload.py:70-79]().
*   **Default Resource**: `https://management.azure.com/` [src/openai/auth/_workload.py:71-71]().

### Google Cloud Platform (GCP)
Uses the GCP Compute Engine metadata server to fetch identity tokens.
*   **Function**: `gcp_id_token_provider(audience, ...)` [src/openai/auth/_workload.py:130-135]().
*   **Default Audience**: `https://api.openai.com/v1` [src/openai/auth/_workload.py:131-131]().

## Token Lifecycle Management

When `workload_identity` is configured, the SDK internally sets the API key to a placeholder string `workload-identity-auth` [src/openai/_client.py:93-93](). The `WorkloadIdentityAuth` class manages a refresh buffer (default 1200 seconds) to ensure tokens are rotated before they expire [src/openai/auth/_workload.py:17-17]().

**Diagram: Token Refresh and Exchange Logic**
```mermaid
sequenceDiagram
    participant BC as BaseClient
    participant WI as WorkloadIdentityAuth
    participant P as SubjectTokenProvider
    participant OAI as OpenAI OAuth Service

    BC->>WI: get_token()
    alt Token in cache AND not expiring soon
        WI-->>BC: Return cached access_token
    else Token missing OR within refresh_buffer_seconds
        WI->>P: get_token()
        P-->>WI: Return Subject JWT/ID Token
        WI->>OAI: POST /oauth/token (grant_type=token-exchange)
        OAI-->>WI: Return new OpenAI Access Token
        WI->>WI: Update cache and expiry
        WI-->>BC: Return new access_token
    end
```
Sources: [src/openai/auth/_workload.py:15-17](), [src/openai/auth/_workload.py:220-250](), [README.md:154-168]().

## Azure OpenAI Authentication

The `AzureOpenAI` client variant supports a different set of authentication mechanisms tailored for Microsoft Azure. Notably, the generic `workload_identity` parameter is not functional in the Azure client [src/openai/lib/azure.py:177-178]().

Instead, Azure authentication uses:
1.  **API Key**: Standard Azure OpenAI service key [src/openai/lib/azure.py:109-109]().
2.  **Azure AD Token**: A static Entra ID (formerly Azure AD) access token [src/openai/lib/azure.py:111-111]().
3.  **Azure AD Token Provider**: A callable (sync or async) that returns a dynamic token [src/openai/lib/azure.py:112-112]().

If Entra ID authentication is used, the SDK employs a sentinel value `API_KEY_SENTINEL` ("`<missing API key>`") for the internal `api_key` field to satisfy base client requirements [src/openai/lib/azure.py:45-45]().

Sources: [src/openai/lib/azure.py:36-62](), [src/openai/lib/azure.py:170-186]().

---

# Page: API Resources and Endpoints

# API Resources and Endpoints

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.stats.yml](.stats.yml)
- [api.md](api.md)
- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)

</details>



This document provides a comprehensive reference for the API resources organized into namespaces within the OpenAI Python SDK. Each resource is accessible as a property on the `OpenAI` or `AsyncOpenAI` client and provides methods for interacting with specific OpenAI API capabilities.

For details about the client instantiation and HTTP infrastructure, see [Core Client Classes](#3). For information about type definitions and validation, see [Data Types and Type System](#5).

**Sources:** [.stats.yml:1-4](), [src/openai/types/__init__.py:1-125]()

---

## Resource Organization

The SDK organizes API endpoints into a hierarchical resource structure accessed via the client object. All resources are defined in `src/openai/resources/` with both synchronous and asynchronous implementations. The `_module_client.py` file exposes these resources through a proxy pattern for convenience.

**Sources:** [src/openai/_module_client.py:36-189](), [src/openai/resources/__init__.py:1-256]()

### Natural Language Space to Code Entity Space

The following diagram bridges the conceptual API resources to their specific class implementations within the SDK.

```mermaid
graph TD
    [OpenAI_Client] --> [Responses_Resource]
    [OpenAI_Client] --> [Chat_Resource]
    [OpenAI_Client] --> [Images_Resource]
    [OpenAI_Client] --> [Audio_Resource]
    [OpenAI_Client] --> [Embeddings_Resource]
    [OpenAI_Client] --> [Files_Resource]
    [OpenAI_Client] --> [VectorStores_Resource]
    [OpenAI_Client] --> [FineTuning_Resource]
    [OpenAI_Client] --> [Batches_Resource]
    [OpenAI_Client] --> [Uploads_Resource]
    [OpenAI_Client] --> [Models_Resource]
    [OpenAI_Client] --> [Moderations_Resource]
    [OpenAI_Client] --> [Beta_Resource]
    [OpenAI_Client] --> [Realtime_Resource]
    [OpenAI_Client] --> [Conversations_Resource]
    [OpenAI_Client] --> [Completions_Resource]
    [OpenAI_Client] --> [Evals_Resource]
    [OpenAI_Client] --> [Containers_Resource]
    [OpenAI_Client] --> [Videos_Resource]
    [OpenAI_Client] --> [Skills_Resource]
    [OpenAI_Client] --> [Admin_Resource]
    
    [Chat_Resource] --> [ChatCompletions_Resource]
    
    [Beta_Resource] --> [Assistants_Resource]
    [Beta_Resource] --> [Threads_Resource]
    
    [Admin_Resource] --> [AdminOrg_Resource]
    
    [Realtime_Resource] --> [RealtimeCalls_Resource]

    subgraph "Code Entities"
    [Responses_Resource]:::code
    [ChatCompletions_Resource]:::code
    [Assistants_Resource]:::code
    end

    classDef code font-family:monospace
```

**Sources:** [src/openai/_module_client.py:168-189](), [src/openai/resources/admin/admin.py:19-22](), [api.md:1-1168]()

---

## Primary Interaction APIs

### Responses API
The Responses API is the modern interface for model interactions, supporting text, images, audio, and files. It provides built-in conversation state management and background processing. The resource supports sub-resources for `input_items` and `input_tokens`.

- **Methods:** `create`, `retrieve`, `delete`, `cancel`, `compact`.
- **Sub-resources:** `input_items`, `input_tokens`.
- **For details, see [Responses API](#4.2)**

**Sources:** [src/openai/resources/responses/responses.py:104-111](), [src/openai/types/responses/response_create_params.py:43-149](), [api.md:26-26]()

### Chat Completions API
The traditional message-based interface for conversational AI. It supports structured outputs through Pydantic model parsing and tool calling. The SDK provides a `parse` method for automatic deserialization into Pydantic models.

- **Methods:** `create`, `retrieve`, `update`, `list`, `delete`, `parse`.
- **Sub-resource:** `messages`.
- **For details, see [Chat Completions API](#4.1)**

**Sources:** [src/openai/resources/chat/completions/completions.py:60-136](), [src/openai/types/chat/completion_create_params.py:42-183](), [api.md:94-104]()

---

## Agentic and Stateful APIs

### Assistants API (Beta)
Designed for building persistent, stateful AI assistants. It manages `Threads` for conversation history and `Runs` for executing an assistant's instructions using tools like `code_interpreter` and `file_search`.

- **Components:** `Assistants`, `Threads`, `Messages`, `Runs`, `Run Steps`.
- **For details, see [Assistants API (Beta)](#4.3)**

**Sources:** [api.md:532-684](), [src/openai/resources/beta/beta.py:1-20]()

### Realtime API (Beta)
Enables low-latency, multi-modal (voice/text) interactions over WebSockets. It includes a `calls` resource for phone and voice integration.

- **Components:** `Session`, `Events`, `Input Audio Buffer`, `Calls`.
- **For details, see [Realtime API (Beta)](#4.9)**

**Sources:** [api.md:865-1001](), [src/openai/_module_client.py:114-117]()

---

## Data and Training APIs

### Fine-Tuning API
Allows training custom models on specific datasets. Supports job management, checkpointing, and integration with third-party tools.

- **Methods:** `create`, `retrieve`, `list`, `cancel`, `checkpoints`.
- **For details, see [Fine-Tuning API](#4.4)**

**Sources:** [api.md:246-333](), [src/openai/_module_client.py:150-154]()

### Embeddings and Vector Stores
Provides tools for semantic search and RAG (Retrieval-Augmented Generation). Embeddings convert text to vectors, while Vector Stores manage the storage and retrieval of these vectors.

- **Resources:** `embeddings`, `vector_stores`.
- **For details, see [Embeddings and Vector Stores](#4.5)**

**Sources:** [api.md:105-116](), [api.md:351-417](), [src/openai/types/embedding.py:1-10]()

### File Management and Uploads
Handles file storage for training, assistant knowledge bases, and batch processing. Supports multi-part uploads for large files via the `uploads` resource.

- **Resources:** `files`, `uploads`.
- **For details, see [File Management and Uploads](#4.6)**

**Sources:** [api.md:117-134](), [api.md:700-725](), [src/openai/resources/files.py:31-118]()

---

## Specialized Content APIs

### Audio, Images, and Video APIs
Dedicated endpoints for non-text modalities.
- **Audio:** Transcription, translation, and speech synthesis.
- **Images:** Generation (`dall-e`), editing, and variations.
- **Video:** Video generation, remixing, and extending.
- **For details, see [Audio, Images, and Video APIs](#4.7)**

**Sources:** [api.md:135-212](), [src/openai/types/__init__.py:6-9](), [src/openai/types/video_create_params.py:1-15]()

---

## Additional API Resources

The SDK also exposes resources for model management, content moderation, bulk processing, and administrative tasks.

| Resource | Purpose |
| :--- | :--- |
| `models` | List and retrieve metadata for available models. |
| `moderations` | Check if content complies with OpenAI usage policies. |
| `batches` | Execute bulk requests asynchronously at lower cost. |
| `evals` | Programmatic evaluation of model performance. |
| `containers` | Manage code execution environments. |
| `skills` | Manage specific model capabilities. |
| `admin` | Organization management (users, projects, usage, invites). |

- **For details, see [Additional API Resources](#4.8)**

**Sources:** [api.md:213-245](), [api.md:685-699](), [src/openai/resources/admin/organization/organization.py:99-144]()

---

## Resource Implementation Mapping

The following diagram shows how high-level method calls on the client map to the underlying resource classes and request parameters.

```mermaid
graph LR
    subgraph "Client Interface"
        [OpenAI_Client]
    end

    subgraph "Resource Classes"
        [Completions_Resource]
        [Responses_Resource]
        [Files_Resource]
        [Admin_Resource]
    end

    subgraph "Parameter Types"
        [CompletionCreateParams]
        [ResponseCreateParams]
        [FileCreateParams]
        [UserListParams]
    end

    [OpenAI_Client] -- ".chat.completions" --> [Completions_Resource]
    [OpenAI_Client] -- ".responses" --> [Responses_Resource]
    [OpenAI_Client] -- ".files" --> [Files_Resource]
    [OpenAI_Client] -- ".admin.organization" --> [Admin_Resource]

    [Completions_Resource] -- "create()" --> [CompletionCreateParams]
    [Responses_Resource] -- "create()" --> [ResponseCreateParams]
    [Files_Resource] -- "create()" --> [FileCreateParams]
    [Admin_Resource] -- "users.list()" --> [UserListParams]
```

**Sources:** [src/openai/resources/chat/completions/completions.py:60-91](), [src/openai/resources/responses/responses.py:133-166](), [src/openai/resources/admin/organization/organization.py:118-119](), [api.md:94-94]()

---

# Page: Chat Completions API

# Chat Completions API

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/chat/__init__.py](src/openai/types/chat/__init__.py)
- [src/openai/types/chat/chat_completion.py](src/openai/types/chat/chat_completion.py)
- [src/openai/types/chat/chat_completion_assistant_message_param.py](src/openai/types/chat/chat_completion_assistant_message_param.py)
- [src/openai/types/chat/chat_completion_chunk.py](src/openai/types/chat/chat_completion_chunk.py)
- [src/openai/types/chat/chat_completion_message.py](src/openai/types/chat/chat_completion_message.py)
- [src/openai/types/chat/chat_completion_message_tool_call.py](src/openai/types/chat/chat_completion_message_tool_call.py)
- [src/openai/types/chat/chat_completion_message_tool_call_param.py](src/openai/types/chat/chat_completion_message_tool_call_param.py)
- [src/openai/types/chat/chat_completion_message_tool_call_union_param.py](src/openai/types/chat/chat_completion_message_tool_call_union_param.py)
- [src/openai/types/chat/chat_completion_tool_param.py](src/openai/types/chat/chat_completion_tool_param.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)
- [tests/compat/test_tool_param.py](tests/compat/test_tool_param.py)

</details>



## Purpose and Scope

The Chat Completions API is a conversational interface for generating text, audio, and tool calls with OpenAI models. While it is supported indefinitely, the [Responses API](#4.2) is now the recommended modern interface for stateful and multi-modal model interactions. This page documents the Chat Completions API resource structure, available methods, and basic usage patterns.

For detailed parameter documentation, see [Parameters and Configuration](#4.1.1). For streaming usage, see [Streaming Chat Completions](#4.1.2). For structured output parsing, see [Parsed Responses and Structured Outputs](#4.1.3).

Sources: [src/openai/resources/chat/completions/completions.py:61-63](), [src/openai/types/chat/completion_create_params.py:37-55]()

---

## Overview

The Chat Completions API enables conversational interactions with OpenAI models through a message-based interface. It is accessed via the `chat.completions` resource on both synchronous and asynchronous clients. The API supports multiple operations: creating completions, retrieving historical completions, updating metadata, listing completions with pagination, and deleting completions.

The resource implements a RESTful pattern with methods that return structured response objects (`ChatCompletion`) or paginated lists (`SyncCursorPage[ChatCompletion]` / `AsyncCursorPage[ChatCompletion]`).

Sources: [src/openai/resources/chat/completions/completions.py:60-90](), [tests/api_resources/chat/test_completions.py:22-120]()

---

## Resource Hierarchy

The Chat Completions API is organized as a nested resource within the SDK's client hierarchy:

```mermaid
graph TB
    OpenAI["OpenAI Client"]
    AsyncOpenAI["AsyncOpenAI Client"]
    
    Chat["chat resource"]
    AsyncChat["chat resource (async)"]
    
    Completions["completions resource<br/>(Completions)"]
    AsyncCompletions["completions resource<br/>(AsyncCompletions)"]
    
    Methods["Methods:<br/>create()<br/>parse()<br/>retrieve()<br/>update()<br/>list()<br/>delete()"]
    
    OpenAI --> Chat
    AsyncOpenAI --> AsyncChat
    
    Chat --> Completions
    AsyncChat --> AsyncCompletions
    
    Completions --> Methods
    AsyncCompletions --> Methods
```

**Access Patterns:**
- Synchronous: `client.chat.completions.create(...)` [src/openai/resources/chat/completions/completions.py:206-250]()
- Asynchronous: `await async_client.chat.completions.create(...)` [src/openai/resources/chat/completions/completions.py:848-892]()
- Parsed: `client.chat.completions.parse(..., response_format=MyModel)` [src/openai/resources/chat/completions/completions.py:91-136]()

Sources: [src/openai/resources/chat/completions/completions.py:60-134](), [tests/api_resources/chat/test_completions.py:27-35]()

---

## Available Methods

The `Completions` resource provides several primary methods for managing the lifecycle of chat interactions:

| Method | Purpose | Return Type | Pagination |
|--------|---------|-------------|------------|
| `create()` | Generate a new chat completion | `ChatCompletion` or `Stream[ChatCompletionChunk]` | No |
| `parse()` | Create with automatic Pydantic parsing | `ParsedChatCompletion[T]` | No |
| `retrieve()` | Fetch a previously created completion | `ChatCompletion` | No |
| `update()` | Update completion metadata | `ChatCompletion` | No |
| `list()` | List historical completions | `SyncCursorPage[ChatCompletion]` | Yes |
| `delete()` | Delete a completion record | `ChatCompletionDeleted` | No |

All methods support response wrapper patterns (`.with_raw_response.method()` and `.with_streaming_response.method()`) for accessing raw HTTP headers and timing.

Sources: [src/openai/resources/chat/completions/completions.py:73-89](), [src/openai/resources/chat/completions/completions.py:91-136](), [tests/api_resources/chat/test_completions.py:123-204]()

---

## Method Signatures and Parameters

### create()

The `create()` method is overloaded to support both standard and streaming responses.

**Non-streaming signature:**
```python
def create(
    messages: Iterable[ChatCompletionMessageParam],
    model: Union[str, ChatModel],
    stream: Optional[Literal[False]] = None,
    **kwargs
) -> ChatCompletion
```

**Streaming signature:**
```python
def create(
    messages: Iterable[ChatCompletionMessageParam],
    model: Union[str, ChatModel],
    stream: Literal[True],
    **kwargs
) -> Stream[ChatCompletionChunk]
```

Required parameters:
- `messages`: A list of `ChatCompletionMessageParam` objects (developer, system, user, assistant, or tool roles). [src/openai/types/chat/completion_create_params.py:43-51]()
- `model`: The model ID (e.g., `gpt-4o`, `o3`). [src/openai/types/chat/completion_create_params.py:53-60]()

Sources: [src/openai/types/chat/completion_create_params.py:37-55](), [src/openai/resources/chat/completions/completions.py:206-250]()

### parse()

A high-level wrapper that automatically handles JSON schema generation and Pydantic deserialization into a `ParsedChatCompletion`. It uses `_type_to_response_format` to convert Pydantic models to API parameters. For details, see [Parsed Responses and Structured Outputs](#4.1.3).

Sources: [src/openai/resources/chat/completions/completions.py:91-136](), [src/openai/resources/chat/completions/completions.py:40-41]()

---

## Request and Response Types

### Request Parameters

The `CompletionCreateParams` type hierarchy defines the structure of the request body:

```mermaid
graph LR
    Base["CompletionCreateParamsBase<br/>(Shared Params)"]
    NonStream["CompletionCreateParamsNonStreaming<br/>stream: False"]
    Stream["CompletionCreateParamsStreaming<br/>stream: True"]
    
    Base --> NonStream
    Base --> Stream
```

**Key Parameters in `CompletionCreateParamsBase`:**
- `messages`: Conversation history including text, images, or audio. [src/openai/types/chat/completion_create_params.py:43-51]()
- `tools`: List of functions the model may call. [src/openai/types/chat/completion_create_params.py:214-218]()
- `reasoning_effort`: Controls computation for reasoning models like `o1`. [src/openai/types/chat/completion_create_params.py:188-193]()
- `web_search_options`: Configures integrated web search capabilities. [src/openai/types/chat/completion_create_params.py:231-235]()

Sources: [src/openai/types/chat/completion_create_params.py:42-235]()

### Response Types

- **ChatCompletion**: The standard response object containing `choices`, `usage`, and `created` timestamp. [src/openai/types/chat/chat_completion.py:191-225]()
- **ChatCompletionChunk**: An incremental update object used during streaming. [src/openai/types/chat/chat_completion_chunk.py:117-182]()
- **ChatCompletionMessage**: The specific content returned within a choice, including `content`, `tool_calls`, and `audio`. [src/openai/types/chat/chat_completion_message.py:12-45]()

Sources: [src/openai/types/chat/chat_completion.py:191-225](), [src/openai/types/chat/chat_completion_chunk.py:117-182]()

---

## Parameter Type System

The SDK uses `TypedDict` for request parameters and `Pydantic` models for responses to ensure type safety.

```mermaid
graph TB
    subgraph "Request Entities (TypedDict)"
        Msg["ChatCompletionMessageParam"]
        Tool["ChatCompletionToolUnionParam"]
        Audio["ChatCompletionAudioParam"]
    end
    
    subgraph "Validation & Transformation"
        Transform["maybe_transform()"]
        PropInfo["PropertyInfo Metadata"]
    end
    
    subgraph "Response Entities (BaseModel)"
        Resp["ChatCompletion"]
        Choice["Choice"]
        Usage["CompletionUsage"]
    end
    
    Msg --> Transform
    Tool --> Transform
    Transform --> API["OpenAI API"]
    API --> Resp
    Resp --> Choice
    Resp --> Usage
```

Sources: [src/openai/types/chat/completion_create_params.py:12-22](), [src/openai/types/chat/chat_completion.py:7-11](), [src/openai/types/chat/chat_completion_message_tool_call.py:12-18]()

---

## Basic Usage Examples

### Synchronous Non-Streaming
```python
from openai import OpenAI

client = OpenAI()
completion = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(completion.choices[0].message.content)
```
Sources: [tests/api_resources/chat/test_completions.py:27-35]()

### Asynchronous Streaming
```python
from openai import AsyncOpenAI

client = AsyncOpenAI()
stream = await client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Tell a story"}],
    stream=True
)
async for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```
Sources: [tests/api_resources/chat/test_completions.py:596-607]()

---

## Error Handling

The Chat Completions API follows the standard SDK error hierarchy. Common exceptions include:
- `BadRequestError`: Invalid parameters (e.g., unsupported model or invalid message structure).
- `RateLimitError`: API quota exceeded.
- `APIConnectionError`: Network issues between the client and OpenAI.

Sources: [src/openai/resources/responses/responses.py:57-57]() (referencing `OpenAIError` and `WebSocketConnectionClosedError`).

---

# Page: Parameters and Configuration

# Parameters and Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/chat/chat_completion_audio_param.py](src/openai/types/chat/chat_completion_audio_param.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/realtime/realtime_audio_config_output.py](src/openai/types/realtime/realtime_audio_config_output.py)
- [src/openai/types/realtime/realtime_audio_config_output_param.py](src/openai/types/realtime/realtime_audio_config_output_param.py)
- [src/openai/types/realtime/realtime_response_create_audio_output.py](src/openai/types/realtime/realtime_response_create_audio_output.py)
- [src/openai/types/realtime/realtime_response_create_audio_output_param.py](src/openai/types/realtime/realtime_response_create_audio_output_param.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [src/openai/types/shared/chat_model.py](src/openai/types/shared/chat_model.py)
- [src/openai/types/shared_params/chat_model.py](src/openai/types/shared_params/chat_model.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/realtime/test_calls.py](tests/api_resources/realtime/test_calls.py)
- [tests/api_resources/realtime/test_client_secrets.py](tests/api_resources/realtime/test_client_secrets.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)

</details>



This page documents all parameters available for the Chat Completions API's `create()` method, covering both standard and streaming modes. These parameters control model behavior, output format, tool usage, reasoning effort, caching, and more.

For information about streaming responses and processing SSE events, see [Streaming Chat Completions](#4.1.2). For structured output parsing and the `parse()` method, see [Parsed Responses and Structured Outputs](#4.1.3). For general client configuration like API keys and timeouts, see [Client Configuration](#2.1).

---

## Parameter Type Definitions

The Chat Completions API uses `TypedDict`-based parameter types that provide type safety while remaining flexible for both streaming and non-streaming modes. All parameters are defined in `src/openai/types/chat/completion_create_params.py`.

### Chat Completion Parameter Hierarchy
Title: Chat Completion Parameter Hierarchy
```mermaid
graph TB
    CompletionCreateParams["CompletionCreateParams<br/>(Union type)"]
    
    CompletionCreateParamsNonStreaming["CompletionCreateParamsNonStreaming<br/>stream: Optional[Literal[False]]"]
    CompletionCreateParamsStreaming["CompletionCreateParamsStreaming<br/>stream: Required[Literal[True]]"]
    
    CompletionCreateParamsBase["CompletionCreateParamsBase<br/>(TypedDict, total=False)<br/>All shared parameters"]
    
    CompletionCreateParams --> CompletionCreateParamsNonStreaming
    CompletionCreateParams --> CompletionCreateParamsStreaming
    
    CompletionCreateParamsNonStreaming --> CompletionCreateParamsBase
    CompletionCreateParamsStreaming --> CompletionCreateParamsBase
    
    CompletionCreateParamsBase --> Required["Required parameters:<br/>messages, model"]
    CompletionCreateParamsBase --> Optional["Optional parameters:<br/>40+ configuration options"]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:24-461]()

The union type `CompletionCreateParams` distinguishes between streaming and non-streaming requests at the type level, enabling proper overload resolution in the client's `create()` method.

---

## Required Parameters

Only two parameters are required for all Chat Completions requests:

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | `Iterable[ChatCompletionMessageParam]` | Conversation history with role-based messages supporting text, images, and audio |
| `model` | `Union[str, ChatModel]` | Model identifier like `gpt-4o`, `o3`, or `gpt-4o-mini` |

**Sources:** [src/openai/types/chat/completion_create_params.py:37-55](), [tests/api_resources/chat/test_completions.py:27-35]()

### Messages Structure

Messages use a role-content structure where each message includes:
- **role**: `developer`, `system`, `user`, `assistant`, or `tool`
- **content**: Text string, array of content parts (text/image/audio), or tool call results
- **name** (optional): Message author identifier

The `messages` parameter is typed as `Required[Iterable[ChatCompletionMessageParam]]` at [src/openai/types/chat/completion_create_params.py:43-51]().

### Model Selection

The `model` parameter accepts either a string or the `ChatModel` enum. Models have different capabilities:
- **GPT-4o series**: Multi-modal, tool calling, structured outputs
- **O-series** (`o3`, `o1`): Reasoning models with `reasoning_effort` control
- **GPT-5 series**: Enhanced reasoning with configurable effort levels (e.g., `gpt-5-mini`, `gpt-5.1`)

**Sources:** [src/openai/types/chat/completion_create_params.py:53-60](), [src/openai/types/shared/chat_model.py:7-89](), [src/openai/types/responses/response_compact_params.py:13-112]()

---

## Output Configuration Parameters

These parameters control the format, structure, and type of model outputs.

### Output Configuration Options
Title: Output Configuration Options
```mermaid
graph LR
    OutputConfig["Output Configuration"]
    
    ResponseFormat["response_format<br/>ResponseFormat"]
    Modalities["modalities<br/>List[Literal['text', 'audio']]"]
    Audio["audio<br/>ChatCompletionAudioParam"]
    MaxTokens["max_completion_tokens<br/>max_tokens"]
    NumChoices["n<br/>int"]
    LogProbs["logprobs<br/>top_logprobs"]
    
    OutputConfig --> ResponseFormat
    OutputConfig --> Modalities
    OutputConfig --> Audio
    OutputConfig --> MaxTokens
    OutputConfig --> NumChoices
    OutputConfig --> LogProbs
    
    ResponseFormat --> Text["ResponseFormatText<br/>type: 'text'"]
    ResponseFormat --> JSONObject["ResponseFormatJSONObject<br/>type: 'json_object'"]
    ResponseFormat --> JSONSchema["ResponseFormatJSONSchema<br/>type: 'json_schema'"]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:57-152](), [src/openai/types/chat/completion_create_params.py:213-224](), [src/openai/types/chat/completion_create_params.py:381]()

### Response Format

| Value | Type | Description |
|-------|------|-------------|
| `{"type": "text"}` | `ResponseFormatText` | Plain text output (default) |
| `{"type": "json_object"}` | `ResponseFormatJSONObject` | Valid JSON object (legacy mode) |
| `{"type": "json_schema", "json_schema": {...}}` | `ResponseFormatJSONSchema` | Structured outputs with JSON Schema validation |

The `response_format` parameter is defined as a `TypeAlias` union at [src/openai/types/chat/completion_create_params.py:381]() and used at [src/openai/types/chat/completion_create_params.py:213-224]().

**Usage in tests:**
```python
# Text format (default)
response_format={"type": "text"}

# JSON Schema for structured outputs
response_format={"type": "json_schema", "json_schema": {...}}
```

**Sources:** [tests/api_resources/chat/test_completions.py:89](), [tests/api_resources/chat/test_completions.py:212]()

### Modalities and Audio

The `modalities` parameter specifies output types:
- `["text"]` - Text-only output (default)
- `["text", "audio"]` - Both text and audio for models like `gpt-4o-audio-preview`

When audio output is requested, the `audio` parameter is required:

```python
audio={
    "format": "wav",  # or "mp3", "opus", "flac", "pcm16"
    "voice": "alloy"  # or "ash", "ballad", "coral", "sage", "shimmer", "verse"
}
```

**Sources:** [src/openai/types/chat/completion_create_params.py:62-67](), [src/openai/types/chat/completion_create_params.py:145-157](), [tests/api_resources/chat/test_completions.py:49-52]()

### Token Limits

| Parameter | Range | Description |
|-----------|-------|-------------|
| `max_completion_tokens` | integer | Total tokens including visible output and reasoning (preferred for o-series) |
| `max_tokens` | integer | Legacy parameter, not compatible with o-series models |

**Sources:** [src/openai/types/chat/completion_create_params.py:117-133]()

---

## Sampling and Generation Control

These parameters influence the randomness, creativity, and style of model responses.

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `temperature` | float | 0-2 | Sampling temperature; higher = more random |
| `top_p` | float | 0-1 | Nucleus sampling; consider tokens with top_p probability mass |
| `frequency_penalty` | float | -2.0 to 2.0 | Penalize tokens by existing frequency |
| `presence_penalty` | float | -2.0 to 2.0 | Penalize tokens by presence in text |
| `logit_bias` | dict | -100 to 100 | Modify likelihood of specific tokens by token ID |
| `seed` | int | any | Enable deterministic sampling (best effort) |
| `stop` | str or list | up to 4 sequences | Stop generation at these sequences |

**Sources:** [src/openai/types/chat/completion_create_params.py:69-108](), [src/openai/types/chat/completion_create_params.py:182-187](), [src/openai/types/chat/completion_create_params.py:235-242](), [src/openai/types/chat/completion_create_params.py:263-268](), [src/openai/types/chat/completion_create_params.py:282-325]()

---

## Tool and Function Calling

Parameters for enabling the model to call external tools and functions.

### Tool Calling Configuration
Title: Tool Calling Configuration
```mermaid
graph TB
    ToolCalling["Tool Calling Configuration"]
    
    Tools["tools<br/>Iterable[ChatCompletionToolUnionParam]"]
    ToolChoice["tool_choice<br/>ChatCompletionToolChoiceOptionParam"]
    ParallelCalls["parallel_tool_calls<br/>bool"]
    
    DeprecatedFunctions["functions<br/>(Deprecated)"]
    DeprecatedFunctionCall["function_call<br/>(Deprecated)"]
    
    ToolCalling --> Tools
    ToolCalling --> ToolChoice
    ToolCalling --> ParallelCalls
    ToolCalling -.->|legacy| DeprecatedFunctions
    ToolCalling -.->|legacy| DeprecatedFunctionCall
    
    Tools --> FunctionTool["Function Tool:<br/>name, description,<br/>parameters, strict"]
    
    ToolChoice --> None["'none'<br/>No tool calls"]
    ToolChoice --> Auto["'auto'<br/>Model decides"]
    ToolChoice --> Required["'required'<br/>Must call tool"]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:76-97](), [src/openai/types/chat/completion_create_params.py:169-175](), [src/openai/types/chat/completion_create_params.py:290-309]()

### Tools Parameter

The `tools` parameter accepts an iterable of tool definitions. Each function tool includes:

```python
tools=[
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"}
                },
                "required": ["location"]
            },
            "strict": True  # Enable strict schema adherence
        }
    }
]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:303-309](), [tests/api_resources/chat/test_completions.py:102-112]()

---

## Reasoning Model Parameters

These parameters are specific to reasoning models (o-series and gpt-5 series) that perform extended thinking before generating responses.

### Reasoning Effort

The `reasoning_effort` parameter constrains computational effort for reasoning models. This is configured via the `ReasoningEffort` literal in `src/openai/types/shared/reasoning_effort.py`.

| Model | Default | Supported Values | Notes |
|-------|---------|------------------|-------|
| `gpt-5.1` | `none` | `none`, `low`, `medium`, `high` | Tools supported at all levels |
| `o1` / `o3` | `medium` | `low`, `medium`, `high` | Standard reasoning range |

**Sources:** [src/openai/types/chat/completion_create_params.py:196-211](), [tests/api_resources/chat/test_completions.py:88]()

### Verbosity

The `verbosity` parameter controls response length and detail:

```python
verbosity="low"     # Concise responses
verbosity="medium"  # Balanced
verbosity="high"    # Detailed, comprehensive responses
```

**Sources:** [src/openai/types/chat/completion_create_params.py:336-342](), [tests/api_resources/chat/test_completions.py:116]()

---

## Caching and Optimization

Parameters that optimize performance and cost through caching and service tier selection.

### Prompt Caching Configuration
Title: Prompt Caching Configuration
```mermaid
graph LR
    PromptCache["Prompt Caching"]
    
    CacheKey["prompt_cache_key<br/>string identifier"]
    Retention["prompt_cache_retention<br/>'in_memory' | '24h'"]
    
    PromptCache --> CacheKey
    PromptCache --> Retention
    
    CacheKey --> Benefits["Benefits:<br/>- Reduced latency<br/>- Lower costs"]
    
    Retention --> InMemory["'in_memory'<br/>Standard caching"]
    Retention --> Extended["'24h'<br/>Extended retention"]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:181-194]()

---

## Web Search Tool (Beta)

The `web_search_options` parameter enables web search capabilities and location-aware searching.

### Web Search Configuration
Title: Web Search Configuration
```mermaid
graph TB
    WebSearch["web_search_options<br/>WebSearchOptions"]
    
    ContextSize["search_context_size<br/>'low' | 'medium' | 'high'"]
    UserLocation["user_location<br/>WebSearchOptionsUserLocation"]
    
    WebSearch --> ContextSize
    WebSearch --> UserLocation
    
    UserLocation --> Approximate["approximate<br/>WebSearchOptionsUserLocationApproximate"]
    
    Approximate --> City["city: string"]
    Approximate --> Country["country: string"]
    Approximate --> Region["region: string"]
    Approximate --> Timezone["timezone: string"]
```

**Sources:** [src/openai/types/chat/completion_create_params.py:344-349](), [src/openai/types/chat/completion_create_params.py:384-430]()

---

## Responses API Comparison

The modern `Responses` API (`src/openai/resources/responses/responses.py`) uses a similar set of parameters but introduces conversation-aware fields like `conversation` and `previous_response_id`.

### Chat Completions vs Responses API Entities
Title: Chat Completions vs Responses API Entities
```mermaid
graph LR
    subgraph ChatCompletionsAPI ["chat.completions.create"]
        Messages["messages: List[ChatCompletionMessageParam]"]
        ModelCC["model: ChatModel"]
    end

    subgraph ResponsesAPI ["responses.create"]
        Input["input: Union[str, ResponseInputParam]"]
        Conversation["conversation: Optional[Conversation]"]
        PrevID["previous_response_id: Optional[str]"]
        ModelR["model: ResponsesModel"]
    end

    Messages -.->|"Mapped To"| Input
    ModelCC --- ModelR
```

**Sources:** [src/openai/types/chat/completion_create_params.py:43-55](), [src/openai/types/responses/response_create_params.py:53-149](), [src/openai/types/responses/responses.py:133-166]()

---

## Type Safety and Validation

The library performs runtime validation through the transformation pipeline. It explicitly prevents passing Pydantic model classes directly to `response_format` in the `create()` method unless using the specialized `parse()` wrapper.

### Request Transformation Flow
Title: Request Transformation Flow
```mermaid
graph LR
    UserCode["User Code:<br/>chat.completions.create(...)"]
    Transform["maybe_transform()<br/>_utils.py"]
    Validate["Type Validation:<br/>PropertyInfo aliases,<br/>format checks"]
    Request["FinalRequestOptions:<br/>HTTP request"]
    
    UserCode --> Transform
    Transform --> Validate
    Validate --> Request
```

**Sources:** [src/openai/resources/chat/completions/completions.py:137-147](), [src/openai/_utils.py:23-33]()

For structured output parsing where you wish to pass a Pydantic model, use the `parse()` method instead which handles the schema generation and response deserialization [src/openai/resources/chat/completions/completions.py:91-136]().

---

# Page: Streaming Chat Completions

# Streaming Chat Completions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_legacy_response.py](src/openai/_legacy_response.py)
- [src/openai/_response.py](src/openai/_response.py)
- [src/openai/_streaming.py](src/openai/_streaming.py)
- [src/openai/lib/_parsing/__init__.py](src/openai/lib/_parsing/__init__.py)
- [tests/lib/chat/test_completions.py](tests/lib/chat/test_completions.py)
- [tests/lib/chat/test_completions_streaming.py](tests/lib/chat/test_completions_streaming.py)
- [tests/lib/responses/__init__.py](tests/lib/responses/__init__.py)
- [tests/lib/responses/test_responses.py](tests/lib/responses/test_responses.py)
- [tests/lib/snapshots.py](tests/lib/snapshots.py)
- [tests/lib/utils.py](tests/lib/utils.py)
- [tests/test_legacy_response.py](tests/test_legacy_response.py)
- [tests/test_response.py](tests/test_response.py)
- [tests/test_streaming.py](tests/test_streaming.py)

</details>



## Purpose and Scope

This page documents streaming functionality for the **Chat Completions API**, which enables incremental delivery of model responses through Server-Sent Events (SSE). Streaming allows applications to display partial results as they arrive rather than waiting for the complete response.

This page covers the Chat Completions API streaming. For streaming with the newer Responses API, see [Responses API](#4.2). For non-streaming Chat Completions usage, see [Chat Completions API](#4.1) and [Parameters and Configuration](#4.1.1). For parsed responses and structured outputs in non-streaming mode, see [Parsed Responses and Structured Outputs](#4.1.3).

---

## Basic Streaming Usage

### Enabling Stream Mode

Set `stream=True` when calling `client.chat.completions.create()` to receive a stream object instead of a complete response. The stream object implements Python's iterator protocol for synchronous clients and async iterator protocol for asynchronous clients.

#### Synchronous Streaming

```python
from openai import OpenAI

client = OpenAI()

stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "Write a haiku about recursion"}
    ],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content is not None:
        print(chunk.choices[0].delta.content, end="")
```

The returned object is a `Stream[ChatCompletionChunk]` which yields `ChatCompletionChunk` objects as they arrive from the API.

**Sources:** [src/openai/_streaming.py:23-50](), [tests/lib/chat/test_completions_streaming.py:47-61]()

#### Asynchronous Streaming

```python
import asyncio
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def main():
    stream = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "Write a haiku about recursion"}
        ],
        stream=True,
    )
    
    async for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            print(chunk.choices[0].delta.content, end="")

asyncio.run(main())
```

The async variant returns an `AsyncStream[ChatCompletionChunk]` which implements the async iterator protocol.

**Sources:** [src/openai/_streaming.py:132-160](), [tests/lib/chat/test_completions_streaming.py:204-214]()

---

## Stream Request Flow

The following diagram illustrates how streaming requests flow through the SDK, from user code to incremental event processing:

### Request and Data Flow

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Client as "OpenAI.chat.completions"
    participant Resp as "APIResponse / AsyncAPIResponse"
    participant Stream as "Stream[T] / AsyncStream[T]"
    participant Decoder as "SSEBytesDecoder"
    participant API as "OpenAI API"
    
    User->>Client: "create(stream=True, ...)"
    Client->>API: "POST /chat/completions"
    API-->>Client: "HTTP 200 (Stream)"
    Client->>Resp: "__init__(stream=True)"
    Resp->>Stream: "_parse(to=Stream[T])"
    
    loop Streaming Chunks
        Stream->>Decoder: "iter_bytes(response.iter_bytes())"
        Decoder-->>Stream: "ServerSentEvent (sse)"
        Stream->>Stream: "sse.json()"
        Stream->>Client: "_process_response_data(data)"
        Stream-->>User: "yield T (e.g. ChatCompletionChunk)"
    end
    
    Stream->>Stream: "close()"
```

**Sources:** [src/openai/_response.py:141-182](), [src/openai/_streaming.py:55-110](), [src/openai/_streaming.py:165-218]()

---

## Stream Event Types

### Core Event Hierarchy

When using the high-level `.stream()` method (rather than `.create(stream=True)`), the SDK emits typed events. All events inherit from `ChatCompletionStreamEvent[ResponseFormatT]`.

```mermaid
graph TB
    BaseEvent["ChatCompletionStreamEvent[T]"]
    
    ChunkEvent["ChunkEvent<br/>type='chunk'"]
    ContentDelta["ContentDeltaEvent[T]<br/>type='content.delta'<br/>delta: str<br/>parsed: Any | None"]
    ContentDone["ContentDoneEvent[T]<br/>type='content.done'<br/>content: str<br/>parsed: T | None"]
    
    ToolCallsDelta["ToolCallsDeltaEvent<br/>type='tool_calls.delta'"]
    ToolCallsDone["ToolCallsDoneEvent<br/>type='tool_calls.done'"]
    
    RefusalDelta["RefusalDeltaEvent<br/>type='refusal.delta'"]
    RefusalDone["RefusalDoneEvent<br/>type='refusal.done'"]
    
    BaseEvent --> ChunkEvent
    BaseEvent --> ContentDelta
    BaseEvent --> ContentDone
    BaseEvent --> ToolCallsDelta
    BaseEvent --> ToolCallsDone
    BaseEvent --> RefusalDelta
    BaseEvent --> RefusalDone
```

| Event Type | Description | Key Properties |
|------------|-------------|----------------|
| `chunk` | Raw `ChatCompletionChunk` from API | `chunk` |
| `content.delta` | Incremental content text | `delta`, `snapshot`, `parsed` |
| `content.done` | Complete content available | `content`, `parsed` |
| `tool_calls.delta` | Incremental tool call data | `delta`, `snapshot` |
| `tool_calls.done` | Complete tool call parsed | `tool_calls` |
| `refusal.delta` | Incremental refusal text | `delta`, `snapshot` |
| `refusal.done` | Complete refusal message | `refusal` |

**Sources:** [tests/lib/chat/test_completions_streaming.py:24-31](), [tests/lib/chat/test_completions_streaming.py:85-94](), [tests/lib/chat/test_completions_streaming.py:183-191]()

---

## Using Stream Managers

### High-Level Stream API

The `.stream()` method returns a `ChatCompletionStreamManager` (or `AsyncChatCompletionStreamManager`) which provides a higher-level interface. It automatically accumulates state and emits semantic events.

```python
from openai import OpenAI
from pydantic import BaseModel

client = OpenAI()

class WeatherResponse(BaseModel):
    city: str
    temperature: float

with client.chat.completions.stream(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What's the weather in SF?"}],
    response_format=WeatherResponse,
) as stream:
    for event in stream:
        if event.type == "content.delta":
            print(event.delta, end="")
        elif event.type == "content.done":
            weather = event.parsed
            print(f"\nParsed: {weather}")
    
    completion = stream.get_final_completion()
```

### Manager vs Direct Stream

| Approach | Return Type | Implementation Class |
|----------|-------------|----------------------|
| `.create(stream=True)` | `Stream[ChatCompletionChunk]` | `openai._streaming.Stream` |
| `.stream()` | `ChatCompletionStreamManager[T]` | `openai.lib.streaming.chat.ChatCompletionStreamManager` |

The manager approach is recommended as it handles incremental parsing of structured outputs and tool calls automatically.

**Sources:** [src/openai/_response.py:141-182](), [tests/lib/chat/test_completions_streaming.py:24-31]()

---

## Stream State Management

### Snapshot Accumulation

`ChatCompletionStream` maintains a `current_completion_snapshot` which accumulates deltas into a complete snapshot object.

### Natural Language to Code Entity Mapping

```mermaid
graph LR
    subgraph "Natural Language Space"
        Concept1["Incremental Response"]
        Concept2["State Management"]
        Concept3["Final Completion"]
    end

    subgraph "Code Entity Space"
        Entity1["ChatCompletionChunk"]
        Entity2["ChatCompletionStreamState"]
        Entity3["accumulate_delta()"]
        Entity4["ParsedChatCompletionSnapshot"]
    end

    Concept1 -.-> Entity1
    Concept2 -.-> Entity2
    Concept2 -.-> Entity3
    Concept3 -.-> Entity4
    
    Entity1 --> Entity2
    Entity2 --> Entity3
    Entity3 --> Entity4
```

The accumulation logic merges chunk data:
- Concatenates string deltas (content, refusal, arguments).
- Appends list items (tool_calls).
- Updates finish reasons and usage stats.

**Sources:** [tests/lib/chat/test_completions_streaming.py:28-30](), [src/openai/_streaming.py:55-107]()

---

## Parsed Streaming (Structured Outputs)

### Incremental JSON Parsing

When using `response_format` with a Pydantic model, the stream manager incrementally parses JSON as it arrives.

```python
for event in stream:
    if event.type == "content.delta":
        # event.parsed contains partial dict/model as JSON accumulates
        print(event.parsed)
```

**Sources:** [tests/lib/chat/test_completions_streaming.py:98-125](), [tests/lib/chat/test_completions_streaming.py:183-191]()

---

## Error Handling in Streams

### API Errors during Streaming

If the API returns an error mid-stream (e.g., a `thread.error` in Assistants or a standard error object in Chat), the `Stream` class raises an `APIError`.

```python
# Internal Stream logic [src/openai/_streaming.py:87-99]
if is_mapping(data) and data.get("error"):
    raise APIError(
        message=data.get("error").get("message"),
        request=self.response.request,
        body=data["error"],
    )
```

**Sources:** [src/openai/_streaming.py:87-99](), [src/openai/_streaming.py:180-192]()

---

## Synchronous vs Asynchronous Streaming

### API Parity

The `Stream` and `AsyncStream` classes provide a unified interface for handling SSE.

| Feature | `Stream[T]` (Sync) | `AsyncStream[T]` (Async) |
|---------|-----------|-------------|
| Iteration | `for item in stream:` | `async for item in stream:` |
| Underlying | `httpx.Response.iter_bytes()` | `httpx.Response.aiter_bytes()` |
| Cleanup | `stream.close()` | `await stream.close()` |

**Sources:** [src/openai/_streaming.py:48-53](), [src/openai/_streaming.py:157-163](), [src/openai/_streaming.py:123-129]()

---

# Page: Parsed Responses and Structured Outputs

# Parsed Responses and Structured Outputs

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_exceptions.py](src/openai/_exceptions.py)
- [src/openai/lib/_parsing/__init__.py](src/openai/lib/_parsing/__init__.py)
- [src/openai/lib/_parsing/_completions.py](src/openai/lib/_parsing/_completions.py)
- [src/openai/lib/_pydantic.py](src/openai/lib/_pydantic.py)
- [src/openai/lib/streaming/chat/__init__.py](src/openai/lib/streaming/chat/__init__.py)
- [src/openai/lib/streaming/chat/_completions.py](src/openai/lib/streaming/chat/_completions.py)
- [tests/lib/chat/test_completions.py](tests/lib/chat/test_completions.py)
- [tests/lib/chat/test_completions_streaming.py](tests/lib/chat/test_completions_streaming.py)
- [tests/lib/responses/__init__.py](tests/lib/responses/__init__.py)
- [tests/lib/responses/test_responses.py](tests/lib/responses/test_responses.py)
- [tests/lib/schema_types/query.py](tests/lib/schema_types/query.py)
- [tests/lib/snapshots.py](tests/lib/snapshots.py)
- [tests/lib/test_pydantic.py](tests/lib/test_pydantic.py)
- [tests/lib/utils.py](tests/lib/utils.py)

</details>



## Purpose and Scope

This document covers the `.parse()` method and structured output capabilities of the Chat Completions API, which automatically deserialize API responses into Pydantic models. This feature enables type-safe, validated responses without manual JSON parsing.

For information about the newer Responses API (the recommended interface for model interactions), see [Responses API](#4.2). For general Chat Completions configuration, see [Parameters and Configuration](#4.1.1). For streaming without structured outputs, see [Streaming Chat Completions](#4.1.2).

---

## Overview

The SDK provides two mechanisms for structured outputs:

1.  **Non-streaming parsing**: `client.chat.completions.parse()` returns a `ParsedChatCompletion[T]` with fully deserialized data.
2.  **Streaming parsing**: `client.chat.completions.stream()` with `response_format` returns incremental parsed data as JSON completes.

Both methods use Pydantic models to define the expected output schema, which the API enforces using JSON Schema with `strict: true` mode.

### Data Flow: Natural Language to Code Entity Space

The following diagram illustrates how a natural language request is transformed into a structured Pydantic model instance through the SDK's parsing layer.

```mermaid
graph LR
    subgraph "User Code Space"
        UserModel["pydantic.BaseModel<br/>(Location)"]
        ParseCall["ChatCompletions.parse()"]
        ParsedResult["ParsedChatCompletion[Location]"]
    end
    
    subgraph "SDK Internal (Code Entity Space)"
        Transform["to_strict_json_schema()"]
        Schema["JSON Schema Generation<br/>src/openai/lib/_pydantic.py"]
        Request["HTTP Request<br/>response_format param"]
    end
    
    subgraph "API Response"
        JSONContent["JSON String<br/>'{\"city\":\"SF\",...}'"]
        RawResponse["ChatCompletion"]
    end
    
    subgraph "Parsing Layer"
        ConstructType["construct_type_unchecked()<br/>src/openai/_models.py"]
        ValidatedModel["Location Instance"]
    end
    
    UserModel --> Transform
    Transform --> Schema
    Schema --> Request
    ParseCall --> Request
    Request --> JSONContent
    JSONContent --> RawResponse
    RawResponse --> ConstructType
    ConstructType --> ValidatedModel
    ValidatedModel --> ParsedResult
    ParsedResult --> UserModel
```

The `client.chat.completions.parse()` method is a wrapper around the standard creation logic that provides richer integrations with Python-specific types and returns a `ParsedChatCompletion` object.

**Sources:** [src/openai/lib/_parsing/_completions.py:86-162](), [src/openai/lib/_pydantic.py:16-25](), [tests/lib/chat/test_completions.py:97-163]()

---

## Basic Usage with Pydantic Models

### Defining Response Schemas

Define the expected response structure using a Pydantic `BaseModel`.

```python
from pydantic import BaseModel
from typing_extensions import Literal

class Location(BaseModel):
    city: str
    temperature: float
    units: Literal["c", "f"]
```

### Calling the Parse Method

Pass the model class to the `response_format` parameter. The SDK uses `to_strict_json_schema` to ensure the model conforms to the API's `strict` requirements [src/openai/lib/_pydantic.py:16-35]().

```python
completion = client.chat.completions.parse(
    model="gpt-4o-2024-08-06",
    messages=[
        {"role": "user", "content": "What's the weather like in SF?"}
    ],
    response_format=Location,
)

# Access the parsed model
location = completion.choices[0].message.parsed
assert isinstance(location, Location)
```

The returned `completion.choices[0].message.parsed` contains a fully instantiated `Location` model with validated fields [src/openai/lib/_parsing/_completions.py:146-150]().

**Sources:** [tests/lib/chat/test_completions.py:97-163](), [src/openai/lib/_pydantic.py:16-35]()

---

## Response Types and Structure

### ParsedChatCompletion[T]

The `.parse()` method returns a generic `ParsedChatCompletion[ResponseFormatT]` object [src/openai/lib/_parsing/_completions.py:86-91]().

```mermaid
classDiagram
    class ParsedChatCompletion~T~ {
        +id: str
        +created: int
        +model: str
        +choices: List[ParsedChoice[T]]
        +usage: CompletionUsage
    }
    
    class ParsedChoice~T~ {
        +index: int
        +message: ParsedChatCompletionMessage[T]
        +finish_reason: str
        +logprobs: ChoiceLogprobs | None
    }
    
    class ParsedChatCompletionMessage~T~ {
        +role: str
        +content: str | None
        +parsed: T | None
        +refusal: str | None
        +tool_calls: List[ParsedFunctionToolCall] | None
    }
    
    class ParsedFunctionToolCall {
        +id: str
        +function: ParsedFunction
        +type: str
    }
    
    class ParsedFunction {
        +name: str
        +arguments: str
        +parsed_arguments: BaseModel | None
    }
    
    ParsedChatCompletion --> ParsedChoice
    ParsedChoice --> ParsedChatCompletionMessage
    ParsedChatCompletionMessage --> ParsedFunctionToolCall
    ParsedFunctionToolCall --> ParsedFunction
```

### Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `message.parsed` | `T \| None` | The deserialized Pydantic model instance [src/openai/lib/_parsing/_completions.py:146-150]() |
| `message.content` | `str \| None` | Raw JSON string from the API |
| `message.refusal` | `str \| None` | Set if the model refuses to respond [src/openai/lib/_parsing/_completions.py:190-195]() |
| `message.tool_calls` | `List[ParsedFunctionToolCall] \| None` | Parsed tool calls with `parsed_arguments` [src/openai/lib/_parsing/_completions.py:107-137]() |

**Sources:** [src/openai/lib/_parsing/_completions.py:86-162](), [tests/lib/chat/test_completions.py:124-162]()

---

## Streaming with Parsing

### Basic Streaming

Use `.stream()` with `response_format` to receive incremental parsing events. The `ChatCompletionStream` manages state and accumulates the partial JSON [src/openai/lib/streaming/chat/_completions.py:46-65]().

```python
with client.chat.completions.stream(
    model="gpt-4o-2024-08-06",
    messages=[{"role": "user", "content": "What's the weather in SF?"}],
    response_format=Location,
) as stream:
    for event in stream:
        if event.type == "content.delta":
            # Partial JSON data as dict
            print(event.parsed)  
        elif event.type == "content.done":
            # Complete parsed model
            print(event.parsed)  
```

### Streaming Event Types

The `ChatCompletionStreamState` class handles the logic for converting raw chunks into high-level events like `content.delta` and `content.done` [src/openai/lib/streaming/chat/_completions.py:65]().

| Event Type | Description | `event.parsed` Type |
|------------|-------------|---------------------|
| `content.delta` | Incremental JSON parsing | `dict[str, Any]` (partial) |
| `content.done` | Complete JSON parsed | `T` (full model instance) |
| `chunk` | Raw `ChatCompletionChunk` | N/A |

**Sources:** [src/openai/lib/streaming/chat/_completions.py:46-119](), [tests/lib/chat/test_completions_streaming.py:98-191]()

---

## Tool Calling with Parsing

### Defining Tools with Pydantic

The SDK validates that tools used with auto-parsing are `strict` and of type `function` [src/openai/lib/_parsing/_completions.py:65-83]().

### Accessing Parsed Tool Arguments

The `parse_function_tool_arguments` utility handles the deserialization of tool call arguments into the specified Pydantic model [src/openai/lib/_parsing/_completions.py:171-188]().

```python
tool_call = completion.choices[0].message.tool_calls[0]
# Parsed model instance
args = tool_call.function.parsed_arguments
```

**Sources:** [src/openai/lib/_parsing/_completions.py:107-137](), [src/openai/lib/_parsing/_completions.py:171-188]()

---

## Error Handling and Edge Cases

### Finish Reasons

The SDK raises specific exceptions if the model stops for reasons other than a complete response [src/openai/_exceptions.py:166-188]():

1.  **LengthFinishReasonError**: Raised when `finish_reason == "length"`, indicating the response was truncated [src/openai/lib/_parsing/_completions.py:99-100]().
2.  **ContentFilterFinishReasonError**: Raised when `finish_reason == "content_filter"` [src/openai/lib/_parsing/_completions.py:102-103]().

### Refusals

If the model refuses to respond, `maybe_parse_content` will return `None`, and the `refusal` property on the message will be populated [src/openai/lib/_parsing/_completions.py:190-195]().

**Sources:** [src/openai/lib/_parsing/_completions.py:97-105](), [src/openai/_exceptions.py:166-188]()

---

## Type Construction Internals

### The construct_type() Logic

Parsing relies on internal construction logic to perform type coercion. This allows the SDK to instantiate models from API responses [src/openai/lib/_parsing/_completions.py:113-125]().

```mermaid
graph TD
    Input["API Response<br/>dict/str/list"]
    
    CheckUnion{"Is Union?"}
    TryValidate["model_validate()"]
    ValidateSuccess["Return validated"]
    
    CheckBaseModel{"Is BaseModel?"}
    CallConstruct["construct_type_unchecked()<br/>src/openai/_models.py"]
    
    Input --> CheckUnion
    CheckUnion -->|Yes| TryValidate
    TryValidate -->|Success| ValidateSuccess
    CheckUnion -->|No| CheckBaseModel
    CheckBaseModel -->|Yes| CallConstruct
    CallConstruct --> ValidateSuccess
```

### JSON Schema Transformation

The `to_strict_json_schema` function in `src/openai/lib/_pydantic.py` mutates standard Pydantic JSON schemas to meet OpenAI's `strict` requirements [src/openai/lib/_pydantic.py:16-35]():
*   Sets `additionalProperties: false` for all objects [src/openai/lib/_pydantic.py:50-51]().
*   Ensures all properties are listed in the `required` array [src/openai/lib/_pydantic.py:57]().
*   Resolves `$ref` pointers to inline definitions where necessary [src/openai/lib/_pydantic.py:100-113]().

**Sources:** [src/openai/lib/_pydantic.py:16-115]()

---

## Comparison: parse() vs create()

| Aspect | `.parse()` | `.create()` |
|--------|-----------|-------------|
| **Return Type** | `ParsedChatCompletion[T]` | `ChatCompletion` |
| **Parsed Access** | `message.parsed` (typed instance) | Manual `json.loads(message.content)` |
| **Tool Arguments** | `parsed_arguments` (typed instance) | Manual `json.loads(tool.arguments)` |
| **Error Handling** | Raises `LengthFinishReasonError` | User must check `finish_reason` |
| **Validation** | Auto-generated via `response_format` | Manual schema in `response_format` |

**Sources:** [src/openai/lib/_parsing/_completions.py:86-162](), [tests/lib/chat/test_completions.py:32-93]()

---

# Page: Responses API

# Responses API

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/lib/_parsing/_responses.py](src/openai/lib/_parsing/_responses.py)
- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/conversations/conversation_item.py](src/openai/types/conversations/conversation_item.py)
- [src/openai/types/responses/__init__.py](src/openai/types/responses/__init__.py)
- [src/openai/types/responses/parsed_response.py](src/openai/types/responses/parsed_response.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/response_item.py](src/openai/types/responses/response_item.py)
- [src/openai/types/responses/response_output_item.py](src/openai/types/responses/response_output_item.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)

</details>



The Responses API is the recommended modern interface for generating model responses in the OpenAI Python library. It provides a unified API for text generation that supersedes the Chat Completions API for new projects by offering improved conversation state management, background execution, and richer output structures.

## Purpose and Scope

This page documents the core `Responses` resource class located at [src/openai/resources/responses/responses.py:104]() and its asynchronous counterpart. It covers:

- Resource class structure and main operations (`create()`, `parse()`, `retrieve()`, `delete()`, `cancel()`, `compact()`)
- Request parameters and response types
- Streaming architecture and event handling
- Integration with the type system and Pydantic models
- Error handling patterns

**See related pages:**
- [Chat Completions API](#4.1) — Legacy interface for conversational interactions
- [Multi-Modal Inputs and Tool Integration](#4.2.1) — Detailed usage of text, images, audio, and tools like computer use or MCP
- [Conversation and State Management](#4.2.2) — Managing context windows, persistence, and compaction

**Sources:** [src/openai/resources/responses/responses.py:104-165](), [src/openai/types/responses/response.py:197-250]()

---

## Resource Class Hierarchy

The Responses API is implemented through the `Responses` and `AsyncResponses` resource classes. These classes manage access to the primary generation endpoints and sub-resources for input items and token counting.

**Resource Class Hierarchy Diagram**

```mermaid
graph TB
    ["OpenAI"] -- "client.responses" --> ["Responses<br/>src/openai/resources/responses/responses.py"]
    ["AsyncOpenAI"] -- "async_client.responses" --> ["AsyncResponses<br/>src/openai/resources/responses/responses.py"]
    
    ["Responses<br/>src/openai/resources/responses/responses.py"] -- "input_items" --> ["InputItems<br/>src/openai/resources/responses/input_items.py"]
    ["Responses<br/>src/openai/resources/responses/responses.py"] -- "input_tokens" --> ["InputTokens<br/>src/openai/resources/responses/input_tokens.py"]
    
    ["AsyncResponses<br/>src/openai/resources/responses/responses.py"] -- "input_items" --> ["AsyncInputItems<br/>src/openai/resources/responses/input_items.py"]
    ["AsyncResponses<br/>src/openai/resources/responses/responses.py"] -- "input_tokens" --> ["AsyncInputTokens<br/>src/openai/resources/responses/input_tokens.py"]
```

**Main Operations Available**

| Method | Return Type | Purpose |
|--------|------------------|---------|
| `create()` | `Response` or `Stream[ResponseStreamEvent]` | Generate a new model response [src/openai/resources/responses/responses.py:133-165]() |
| `parse()` | `ParsedResponse[T]` | Generate a response parsed into a Pydantic model [src/openai/resources/responses/responses.py:687-700]() |
| `retrieve()` | `Response` | Fetch an existing response by ID [src/openai/resources/responses/responses.py:854-860]() |
| `delete()` | `None` | Delete a stored response [src/openai/resources/responses/responses.py:1128-1132]() |
| `cancel()` | `Response` | Cancel an in-progress background response [src/openai/resources/responses/responses.py:1182-1186]() |
| `compact()` | `CompactedResponse` | Compact conversation history to save tokens [src/openai/resources/responses/responses.py:1236-1240]() |

**Sources:** [src/openai/resources/responses/responses.py:104-1240]()

---

## Core Operations

### create()

The `create()` method generates a new model response. It supports both synchronous and streaming modes via the `stream` parameter [src/openai/resources/responses/responses.py:157](). It accepts complex inputs including `ResponseInputParam` which can encapsulate messages, tool outputs, and more [src/openai/types/responses/response_create_params.py:83]().

**Sources:** [src/openai/resources/responses/responses.py:133-165](), [src/openai/types/responses/response_create_params.py:43-172]()

### parse()

The `parse()` method enables **Structured Outputs** by accepting a Pydantic model class as the `text_format` [src/openai/resources/responses/responses.py:692](). It automatically converts the model to a JSON schema for the model and parses the resulting text back into the Pydantic instance.

**Type Transformation Pipeline Diagram**

```mermaid
graph LR
    ["Pydantic BaseModel<br/>(User Defined)"] -- "type_to_text_format_param()" --> ["TextFormatT<br/>src/openai/lib/_parsing/_responses.py"]
    ["TextFormatT<br/>src/openai/lib/_parsing/_responses.py"] -- "API Request" --> ["Response<br/>src/openai/types/responses/response.py"]
    ["Response<br/>src/openai/types/responses/response.py"] -- "parse_response()" --> ["ParsedResponse[T]<br/>src/openai/types/responses/parsed_response.py"]
```

**Sources:** [src/openai/resources/responses/responses.py:687-852](), [src/openai/lib/_parsing/_responses.py:66-70](), [src/openai/types/responses/parsed_response.py:112-127]()

### retrieve(), delete(), and cancel()

- **retrieve()**: Fetches a response object by its ID [src/openai/resources/responses/responses.py:854](). Can also re-stream a response by setting `stream=True` [src/openai/resources/responses/responses.py:869]().
- **delete()**: Permanently removes a response and its associated items [src/openai/resources/responses/responses.py:1128]().
- **cancel()**: Stops a response that is currently in a `queued` or `in_progress` state [src/openai/resources/responses/responses.py:1182]().

### compact()

The `compact()` method is used to manage the context window by summarizing or pruning conversation history [src/openai/resources/responses/responses.py:1236](). It returns a `CompactedResponse` which helps maintain context efficiently in subsequent calls.

**Sources:** [src/openai/resources/responses/responses.py:1236-1288](), [src/openai/types/responses/compacted_response.py:1-41]()

---

## Request Parameters

The `create()` method accepts parameters defined in `ResponseCreateParams` [src/openai/types/responses/response_create_params.py:43-172]().

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | `ResponsesModel` | The ID of the model to use (e.g., `gpt-4o`, `o3`) [src/openai/types/responses/response_create_params.py:128](). |
| `input` | `str \| ResponseInputParam` | The primary input content (text, image, or file) [src/openai/types/responses/response_create_params.py:83](). |
| `instructions` | `str` | System-level instructions for the model [src/openai/types/responses/response_create_params.py:95](). |
| `previous_response_id`| `str` | ID of the previous response to continue a conversation [src/openai/types/responses/response_create_params.py:143](). |
| `tools` | `Iterable[ToolParam]` | List of tools available to the model [src/openai/types/responses/response_create_params.py:195](). |
| `background` | `bool` | If true, the response is generated in the background [src/openai/types/responses/response_create_params.py:44](). |

**Sources:** [src/openai/types/responses/response_create_params.py:43-201]()

---

## Response Object Structure

The `Response` model [src/openai/types/responses/response.py:197]() contains the generated output and metadata.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier for the response [src/openai/types/responses/response.py:198](). |
| `status` | `ResponseStatus` | Current state of the response generation [src/openai/types/responses/response.py:236](). |
| `output` | `List[ResponseOutputItem]` | List of generated items (text, tool calls, etc.) [src/openai/types/responses/response.py:228](). |
| `usage` | `ResponseUsage` | Token usage breakdown [src/openai/types/responses/response.py:245](). |
| `error` | `ResponseError` | Error details if the generation failed [src/openai/types/responses/response.py:204](). |

**Sources:** [src/openai/types/responses/response.py:197-250](), [src/openai/types/responses/response_status.py:1-12]()

---

## Streaming and Event Handling

When `stream=True` is used, the API emits `ResponseStreamEvent` objects [src/openai/types/responses/response_stream_event.py:1](). The SDK manages these via `ResponseStreamManager` and `AsyncResponseStreamManager` [src/openai/lib/streaming/responses/_responses.py:78]().

**Common Event Types:**
- `response.created`: Initial response object.
- `output_item.delta`: Incremental content (text chunks or tool arguments).
- `response.done`: Final state of the response.

**Sources:** [src/openai/types/responses/response_stream_event.py:1-100](), [src/openai/lib/streaming/responses/_responses.py:78]()

---

## Error Handling

Errors can occur during the HTTP request or during the model's background generation. Background errors are captured in the `error` field of the `Response` object [src/openai/types/responses/response.py:204]().

**Sources:** [src/openai/types/responses/response_error.py:1-15](), [src/openai/_exceptions.py:57]()

---

# Page: Multi-Modal Inputs and Tool Integration

# Multi-Modal Inputs and Tool Integration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/images.py](src/openai/resources/images.py)
- [src/openai/types/image_edit_params.py](src/openai/types/image_edit_params.py)
- [src/openai/types/image_generate_params.py](src/openai/types/image_generate_params.py)
- [src/openai/types/responses/computer_tool.py](src/openai/types/responses/computer_tool.py)
- [src/openai/types/responses/computer_tool_param.py](src/openai/types/responses/computer_tool_param.py)
- [src/openai/types/responses/namespace_tool.py](src/openai/types/responses/namespace_tool.py)
- [src/openai/types/responses/namespace_tool_param.py](src/openai/types/responses/namespace_tool_param.py)
- [src/openai/types/responses/response_function_web_search.py](src/openai/types/responses/response_function_web_search.py)
- [src/openai/types/responses/response_function_web_search_param.py](src/openai/types/responses/response_function_web_search_param.py)
- [src/openai/types/responses/response_input_item.py](src/openai/types/responses/response_input_item.py)
- [src/openai/types/responses/response_input_item_param.py](src/openai/types/responses/response_input_item_param.py)
- [src/openai/types/responses/response_input_param.py](src/openai/types/responses/response_input_param.py)
- [src/openai/types/responses/tool.py](src/openai/types/responses/tool.py)
- [src/openai/types/responses/tool_param.py](src/openai/types/responses/tool_param.py)
- [tests/api_resources/test_images.py](tests/api_resources/test_images.py)

</details>



## Purpose and Scope

This page documents how the Responses API handles multi-modal inputs and tool integration within the OpenAI Python SDK. It covers the `input` parameter for providing text, images, and file content, the `tools` parameter for defining callable functions and built-in capabilities, and the integration of specialized tools such as Web Search, Computer Use, and Model Context Protocol (MCP) servers.

For information about conversation state management, see [Conversation and State Management](#4.2.2).

## Multi-Modal Input Parameter

The `input` parameter in the Responses API accepts either a plain string for simple text or structured multi-modal content via `ResponseInputItemParam` and `ResponseInputParam`.

### Input Type Structure

The input system uses a discriminated union pattern to handle different content types and message roles.

| Modality | Implementation Class | Description |
|----------|----------------------|-------------|
| **Message** | `Message` | A message input with roles `user`, `system`, or `developer`. |
| **Tool Call Output** | `FunctionCallOutput` | The result of a previous function tool call. |
| **Computer Output** | `ComputerCallOutput` | Screenshot data returned from a computer tool. |
| **MCP Integration** | `McpCall` | Interaction data for Model Context Protocol servers. |

**Sources:** [src/openai/types/responses/response_input_item_param.py:78-103](), [src/openai/types/responses/response_input_item_param.py:119-147](), [src/openai/types/responses/response_input_item_param.py:164-191]()

### Input Processing Flow

The following diagram illustrates how multi-modal inputs are transformed from Python types into API-ready payloads.

```mermaid
graph TB
    UserInput["User input parameter"]
    CheckType{"Input type?"}
    StringPath["str"]
    ParamPath["ResponseInputItemParam"]
    
    subgraph "Data Transformation Space"
        Transform["maybe_transform()<br/>src/openai/_utils.py"]
        Extract["extract_files()<br/>src/openai/_utils.py"]
    end
    
    APIRequest["HTTP POST /responses"]
    
    UserInput --> CheckType
    CheckType --> StringPath
    CheckType --> ParamPath
    StringPath --> Transform
    ParamPath --> Transform
    Transform --> Extract
    Extract --> APIRequest
    
    subgraph "Code Entity Space"
        T1["ResponseInputMessageContentListParam"]
        T2["ResponseComputerToolCallOutputScreenshotParam"]
        T3["ResponseFunctionCallOutputItemListParam"]
    end
    
    ParamPath -.-> T1
    ParamPath -.-> T2
    ParamPath -.-> T3
```

**Input Transformation Flow Diagram**

**Sources:** [src/openai/resources/images.py:109-117](), [src/openai/_utils.py:14-14](), [src/openai/types/responses/response_input_item_param.py:23-27]()

## Tool Definitions and Integration

The `tools` parameter accepts an iterable of `ToolParam` objects. These define capabilities the model can invoke, ranging from custom Python functions to complex remote interactions.

### Tool Categories

The SDK organizes tools into several distinct functional categories:

| Category | Type Literal | Implementation |
|----------|--------------|----------------|
| **Function** | `function` | Custom user-defined functions via `FunctionToolParam`. |
| **Web Search** | `web_search` | Built-in internet search via `WebSearchToolParam`. |
| **Computer Use** | `computer` | Control of a virtual computer via `ComputerToolParam`. |
| **MCP** | `mcp` | Remote tools via Model Context Protocol via `Mcp`. |
| **File Search** | `file_search` | Retrieval augmented generation via `FileSearchToolParam`. |

**Sources:** [src/openai/types/responses/tool_param.py:11-24](), [src/openai/types/responses/tool.py:24-41](), [src/openai/types/responses/computer_tool.py:10-17]()

### Model Context Protocol (MCP) Integration

The SDK supports the Model Context Protocol, allowing models to interact with remote servers or service connectors. The `Mcp` class manages connection details including `server_url`, `connector_id` (e.g., `connector_gmail`), and `authorization` tokens.

**Sources:** [src/openai/types/responses/tool_param.py:115-194](), [src/openai/types/responses/tool.py:113-195]()

### Computer Use and Web Search

Specialized tool call results like `ResponseFunctionWebSearch` provide structured feedback on complex multi-step actions, including specific actions like `search`, `open_page`, and `find_in_page`.

```mermaid
graph LR
    subgraph "Natural Language Space"
        Action["'Search for OpenAI news'"]
        Interaction["'Take a screenshot'"]
    end

    subgraph "Code Entity Space"
        WS["ResponseFunctionWebSearch<br/>src/openai/types/responses/"]
        CU["ResponseComputerToolCall<br/>src/openai/types/responses/"]
        
        Action --> WS
        Interaction --> CU
        
        WS --- WST["type: 'web_search_call'"]
        CU --- CUT["type: 'computer_call'"]
    end
```

**Tool Response Entity Mapping**

**Sources:** [src/openai/types/responses/response_function_web_search.py:71-92](), [src/openai/types/responses/response_input_item.py:118-144]()

## Image Generation and Editing

While the Responses API handles multi-modal input, the `Images` resource handles dedicated generation and editing tasks using models like `dall-e-3` or the `gpt-image` series.

### Image Resource Methods

- `generate`: Creates an image from a text prompt. [src/openai/resources/images.py:176-180]()
- `edit`: Modifies an existing image based on a prompt and optional mask. [src/openai/resources/images.py:129-154]()
- `create_variation`: Generates a variation of a provided image (DALL-E 2 only). [src/openai/resources/images.py:50-65]()

### Parameters and Streaming
For GPT image models, the SDK supports `stream=True`, which returns an `ImageGenStreamEvent` or `ImageEditStreamEvent`. This allows processing partial images or progress updates.

**Sources:** [src/openai/resources/images.py:22-23](), [src/openai/types/image_generate_params.py:149-157](), [src/openai/types/image_edit_params.py:150-158]()

## Implementation Details

### Tool Call Statuses
Tools within the Responses API lifecycle move through specific statuses:
- `ResponseFunctionWebSearch`: `in_progress`, `searching`, `completed`, `failed`. [src/openai/types/responses/response_function_web_search.py:87-88]()
- `Message`: `in_progress`, `completed`, `incomplete`. [src/openai/types/responses/response_input_item.py:93-98]()

### Data Transformation
The SDK uses `extract_files` and `deepcopy_with_paths` to prepare multi-part form data when images or files are passed as raw bytes or file-like objects.

**Sources:** [src/openai/resources/images.py:98-117](), [src/openai/_utils.py:14-14]()

---

# Page: Conversation and State Management

# Conversation and State Management

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/conversations/conversations.py](src/openai/resources/conversations/conversations.py)
- [src/openai/resources/conversations/items.py](src/openai/resources/conversations/items.py)
- [src/openai/resources/responses/input_items.py](src/openai/resources/responses/input_items.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/chat/completion_list_params.py](src/openai/types/chat/completion_list_params.py)
- [src/openai/types/conversations/conversation_create_params.py](src/openai/types/conversations/conversation_create_params.py)
- [src/openai/types/conversations/conversation_update_params.py](src/openai/types/conversations/conversation_update_params.py)
- [src/openai/types/conversations/item_list_params.py](src/openai/types/conversations/item_list_params.py)
- [src/openai/types/conversations/message.py](src/openai/types/conversations/message.py)
- [src/openai/types/conversations/summary_text_content.py](src/openai/types/conversations/summary_text_content.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_content_part_added_event.py](src/openai/types/responses/response_content_part_added_event.py)
- [src/openai/types/responses/response_content_part_done_event.py](src/openai/types/responses/response_content_part_done_event.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)

</details>



This page documents how to manage conversation state and context when using the Responses API. It covers the primary mechanisms for multi-turn conversations (`previous_response_id` and `conversation`), context window management strategies, and the persistent `Conversations` resource.

---

## Overview

The Responses API provides two distinct mechanisms for managing conversation state across multiple API calls:

| Approach | Management Style | Use Case | State Location |
|----------|-----------------|----------|----------------|
| `previous_response_id` | Stateless chaining | Manual control, explicit state passing | Client-managed reference |
| `conversation` | Automatic state tracking | Simplified multi-turn flows | Server-managed persistence |

Both approaches enable multi-turn conversations where the model retains context from previous interactions, but they differ in how state is maintained and passed between requests.

**Sources:** [src/openai/resources/responses/responses.py:131-165](), [src/openai/types/responses/response.py:197-216]()

---

## State Management with `previous_response_id`

### Stateless Conversation Chaining

The `previous_response_id` parameter creates a stateless chain of responses where each request explicitly references its predecessor. The SDK client does not automatically track conversation state—developers must manually pass the response ID from one call to the next.

**Diagram: Stateless Chaining with `previous_response_id`**

```mermaid
sequenceDiagram
    participant Client
    participant ResponsesAPI as "Responses"
    participant OpenAI as "OpenAI Backend"
    
    Note over Client, OpenAI: Implementation in src/openai/resources/responses/responses.py
    
    Client->>ResponsesAPI: "create(input='Hello')"
    ResponsesAPI->>OpenAI: "POST /responses"
    OpenAI-->>ResponsesAPI: "Response(id='resp_001')"
    ResponsesAPI-->>Client: "Response(id='resp_001')"
    
    Note over Client: Client stores resp_001
    
    Client->>ResponsesAPI: "create(input='Follow-up', previous_response_id='resp_001')"
    ResponsesAPI->>OpenAI: "POST /responses {previous_response_id: 'resp_001'}"
    Note over OpenAI: OpenAI fetches resp_001<br/>context from storage
    OpenAI-->>ResponsesAPI: "Response(id='resp_002')"
    ResponsesAPI-->>Client: "Response(id='resp_002')"
```

**Sources:** [src/openai/resources/responses/responses.py:147](), [src/openai/types/responses/response.py:198-216]()

### Key Characteristics

- **Context Inheritance**: The new response inherits the full conversation context (input items and output items) from the referenced response [src/openai/types/responses/response_create_params.py:143-147]().
- **Instruction Override**: When specified with `previous_response_id`, the `instructions` parameter replaces the system message from the previous response rather than appending to it [src/openai/types/responses/response.py:210-216]().
- **Mutual Exclusivity**: Cannot be used simultaneously with the `conversation` parameter [src/openai/types/responses/response_create_params.py:148-149]().
- **Storage Requirement**: The referenced response must have been created with `store=True` (or stored by default) to be accessible [src/openai/types/responses/response_create_params.py:155-155]().

---

## State Management with `conversation`

### Server-Managed State

The `conversation` parameter enables server-managed state where the API automatically appends input and output items to a persistent conversation object.

**Diagram: Conversation State Transitions**

```mermaid
graph TB
    subgraph "Request 1"
        R1["Responses.create(conversation='conv_123', input='Hello')"]
    end
    
    subgraph "Conversation conv_123 State"
        direction TB
        C1["Items: []"]
        C2["Items: [user: Hello, assistant: Hi!]"]
        C3["Items: [..., user: Tell me more, assistant: Sure...]"]
    end
    
    subgraph "Request 2"
        R2["Responses.create(conversation='conv_123', input='Tell me more')"]
    end
    
    R1 --> C1
    C1 --> |"API appends items"| C2
    C2 --> R2
    R2 --> |"API appends items"| C3
    
    style R1 stroke-dasharray: 5 5
    style R2 stroke-dasharray: 5 5
```

**Sources:** [src/openai/types/responses/response_create_params.py:53-59](), [src/openai/types/responses/response.py:70-79, 197-203]()

### The Conversations Resource

The `Conversations` resource allows for explicit management of these persistent state objects, separate from individual response generations.

- **Create**: Initialize a new conversation via `client.conversations.create()` with optional starting items [src/openai/resources/conversations/conversations.py:60-111]().
- **Retrieve**: Fetch the current state and metadata of a conversation [src/openai/resources/conversations/conversations.py:113-148]().
- **Update**: Modify metadata associated with the conversation [src/openai/resources/conversations/conversations.py:150-193]().
- **Delete**: Remove the conversation and its history [src/openai/resources/conversations/conversations.py:195-230]().

**Sources:** [src/openai/resources/conversations/conversations.py:33-230]()

---

## Context Window Management

### Truncation Strategy

The `truncation` parameter in the Responses API controls automatic context window overflow handling [src/openai/types/responses/response_create_params.py:164-164]():

| Value | Behavior |
|-------|----------|
| `"disabled"` | No automatic truncation. Returns 400 error if context exceeds model limit. |
| `"auto"` | Automatic truncation enabled. Drops items from the beginning of the conversation to fit. |

**Sources:** [src/openai/resources/responses/responses.py:164](), [src/openai/types/responses/response_create_params.py:164-164]()

### Compaction

The `compact()` method explicitly compresses a conversation history by summarizing or removing items to reduce token usage.

**Diagram: Compaction Flow**

```mermaid
graph LR
    subgraph "Before Compact"
        direction TB
        I1["History: [1] user: question, [2] assistant: answer, ... [20] user: latest"]
        T1["Total: 15,000 tokens"]
    end
    
    subgraph "compact Method"
        direction TB
        C["Responses.compact(model='gpt-5.4', previous_response_id='resp_123')"]
    end
    
    subgraph "After Compact"
        direction TB
        I2["Compacted Items: [summary] system: summary, [19] user: recent, [20] user: latest"]
        T2["Total: 3,000 tokens"]
    end
    
    I1 --> C
    C --> I2
    T1 -.-> T2
```

**Sources:** [src/openai/resources/responses/responses.py:62](), [src/openai/types/responses/response_compact_params.py:13-166]()

### Context Management Configuration

Requests can include a `context_management` parameter to define automatic behavior, such as setting thresholds for when compaction should be triggered [src/openai/types/responses/responses_client_event_param.py:41-47]().

- **type**: Currently only `"compaction"` is supported [src/openai/types/responses/responses_client_event_param.py:42]().
- **compact_threshold**: Token threshold at which compaction should be triggered for this entry [src/openai/types/responses/responses_client_event_param.py:45]().

**Sources:** [src/openai/types/responses/responses_client_event_param.py:41-47](), [src/openai/resources/responses/responses.py:136]()

---

## Response Storage and Retrieval

### The `store` Parameter

The `store` parameter controls whether responses are persisted in the OpenAI backend [src/openai/types/responses/response_create_params.py:155-155]():

- `True`: Response is stored. Enables retrieval via `retrieve()` and allows referencing via `previous_response_id`.
- `False`: Response is not persisted. Useful for minimizing data retention or purely stateless operations.

**Sources:** [src/openai/resources/responses/responses.py:155](), [src/openai/types/responses/response_create_params.py:155-155]()

### Encrypted Reasoning in Stateless Turns

When using reasoning models in stateless mode (`store=false`), reasoning tokens are not stored. To enable multi-turn conversations in this mode, use the `include` parameter:

```python
include=["reasoning.encrypted_content"]
```

This includes an encrypted version of reasoning tokens in the response output. These can be passed back in the `input` of a subsequent turn to provide the model with its previous reasoning context without server-side storage.

**Sources:** [src/openai/types/responses/response_create_params.py:76-80](), [src/openai/resources/responses/responses.py:138]()

---

## Code Entities Summary

| Class / Type | File Path | Role |
|--------------|-----------|------|
| `Responses` | [src/openai/resources/responses/responses.py:103]() | Main resource for generating responses and compacting history. |
| `Conversations` | [src/openai/resources/conversations/conversations.py:33]() | Resource for managing persistent conversation objects. |
| `Response` | [src/openai/types/responses/response.py:197]() | The Pydantic model representing a generated response and its state metadata. |
| `ResponseCreateParams` | [src/openai/types/responses/response_create_params.py:27]() | TypedDict defining parameters for state management in creation requests. |
| `ResponseCompactParams` | [src/openai/types/responses/response_compact_params.py:13]() | Parameters for the compaction process. |
| `ContextManagement` | [src/openai/types/responses/responses_client_event_param.py:41]() | Configuration for automatic context handling (compaction). |

**Sources:** [src/openai/resources/responses/responses.py](), [src/openai/resources/conversations/conversations.py](), [src/openai/types/responses/response.py](), [src/openai/types/responses/response_create_params.py]()

---

# Page: Assistants API (Beta)

# Assistants API (Beta)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/audio/audio.py](src/openai/resources/audio/audio.py)
- [src/openai/resources/beta/assistants.py](src/openai/resources/beta/assistants.py)
- [src/openai/resources/beta/beta.py](src/openai/resources/beta/beta.py)
- [src/openai/resources/beta/threads/runs/runs.py](src/openai/resources/beta/threads/runs/runs.py)
- [src/openai/resources/beta/threads/threads.py](src/openai/resources/beta/threads/threads.py)
- [src/openai/resources/fine_tuning/fine_tuning.py](src/openai/resources/fine_tuning/fine_tuning.py)
- [src/openai/types/beta/assistant.py](src/openai/types/beta/assistant.py)
- [src/openai/types/beta/assistant_create_params.py](src/openai/types/beta/assistant_create_params.py)
- [src/openai/types/beta/assistant_update_params.py](src/openai/types/beta/assistant_update_params.py)
- [src/openai/types/beta/thread_create_and_run_params.py](src/openai/types/beta/thread_create_and_run_params.py)
- [src/openai/types/beta/threads/run.py](src/openai/types/beta/threads/run.py)
- [src/openai/types/beta/threads/run_create_params.py](src/openai/types/beta/threads/run_create_params.py)
- [src/openai/types/chat_model.py](src/openai/types/chat_model.py)

</details>



**Deprecation Notice**: The Assistants API is deprecated in favor of the Responses API. All methods in this API are marked with deprecation warnings [src/openai/resources/beta/threads/runs/runs.py:90-90](). For new applications, see [Responses API](#4.2).

## Purpose and Scope

The Assistants API provides a framework for building stateful AI agents with persistent conversation threads, tool integration (code execution, file search, function calling), and multi-turn execution. This document covers:

- Creating and managing assistants with instructions, tools, and tool resources.
- Thread-based conversation management with messages.
- Run lifecycle for executing assistants on threads.
- Tool integration including `code_interpreter`, `file_search`, and custom functions.
- Streaming run events and handling required actions.

For detailed information on specific components, see the following child pages:
- [Assistants and Configuration](#4.3.1) — Creating and managing assistants, instructions, and tools.
- [Threads and Messages](#4.3.2) — Managing conversation state and adding messages.
- [Runs and Execution](#4.3.3) — The run lifecycle, state machine, and required actions.
- [Streaming Assistant Events](#4.3.4) — Processing real-time events and incremental responses.

---

## System Architecture

The Assistants API consists of primary resources organized hierarchically under the `beta` namespace [src/openai/resources/beta/beta.py:6-30](). The SDK uses a resource-based pattern where sub-resources are accessed via cached properties on their parents.

### Resource Hierarchy

```mermaid
graph TB
    subgraph "Client Entry Point"
        CLIENT["OpenAI / AsyncOpenAI"]
        BETA["client.beta (Beta)"]
    end
    
    subgraph "Primary Resources"
        ASSISTANTS["Assistants<br/>(resources/beta/assistants.py)"]
        THREADS["Threads<br/>(resources/beta/threads/threads.py)"]
    end
    
    subgraph "Thread Sub-Resources"
        MESSAGES["Messages<br/>(resources/beta/threads/messages.py)"]
        RUNS["Runs<br/>(resources/beta/threads/runs/runs.py)"]
    end
    
    subgraph "Run Sub-Resources"
        STEPS["Steps<br/>(resources/beta/threads/runs/steps.py)"]
    end
    
    subgraph "Core Models (Pydantic)"
        ASSISTANT_MODEL["Assistant<br/>(types/beta/assistant.py)"]
        THREAD_MODEL["Thread<br/>(types/beta/thread.py)"]
        RUN_MODEL["Run<br/>(types/beta/threads/run.py)"]
    end
    
    CLIENT --> BETA
    BETA --> ASSISTANTS
    BETA --> THREADS
    
    THREADS --> MESSAGES
    THREADS --> RUNS
    RUNS --> STEPS
    
    ASSISTANTS -.-> ASSISTANT_MODEL
    THREADS -.-> THREAD_MODEL
    RUNS -.-> RUN_MODEL
```

**Sources**: [src/openai/resources/beta/beta.py:48-73](), [src/openai/resources/beta/assistants.py:35-38](), [src/openai/resources/beta/threads/threads.py:62-73](), [src/openai/resources/beta/threads/runs/runs.py:62-68]()

---

## Assistants

Assistants are stateful AI agents configured with a model, instructions, and tools. They serve as the blueprint for conversation execution.

### Assistant Configuration

Assistants are created via `client.beta.assistants.create()` [src/openai/resources/beta/assistants.py:58](). Key parameters include `model`, `instructions`, and `tools` (e.g., `code_interpreter`, `file_search`, or `function`) [src/openai/types/beta/assistant_create_params.py:28-112]().

```mermaid
graph LR
    CREATE["Assistants.create()"]
    PARAMS["AssistantCreateParams<br/>(types/beta/assistant_create_params.py)"]
    TRANSFORM["maybe_transform()"]
    Cast["Assistant<br/>(types/beta/assistant.py)"]

    CREATE --> PARAMS
    PARAMS --> TRANSFORM
    TRANSFORM --> Cast
    
    subgraph "Configurable Entities"
        MODEL["model: str | ChatModel"]
        TOOLS["tools: AssistantToolParam"]
        RESOURCES["tool_resources: ToolResources"]
        REASONING["reasoning_effort: ReasoningEffort"]
    end
    
    PARAMS --> MODEL
    PARAMS --> TOOLS
    PARAMS --> RESOURCES
    PARAMS --> REASONING
```

For details, see [Assistants and Configuration](#4.3.1).

**Sources**: [src/openai/resources/beta/assistants.py:58-78](), [src/openai/types/beta/assistant_create_params.py:28-125](), [src/openai/types/beta/assistant_update_params.py:17-161]()

---

## Threads and Messages

Threads represent a session between a user and an assistant. They store `Messages`, which contain text, images, or attachments used by tools.

| Component | SDK Access | Description |
|-----------|------------|-------------|
| **Thread** | `client.beta.threads` | Persistent conversation container [src/openai/resources/beta/threads/threads.py:62-63]() |
| **Message** | `client.beta.threads.messages` | Individual turns in a thread [src/openai/resources/beta/threads/threads.py:71-73]() |
| **Tool Resources** | `tool_resources` | File IDs for code interpreter or vector stores for file search [src/openai/types/beta/thread_create_and_run_params.py:147-153]() |

For details, see [Threads and Messages](#4.3.2).

**Sources**: [src/openai/resources/beta/threads/threads.py:95-154](), [src/openai/types/beta/thread_create_and_run_params.py:129-159]()

---

## Runs and Execution

A `Run` is an invocation of an assistant on a thread. The SDK manages the run lifecycle, which includes handling tool calls through "Required Actions" [src/openai/types/beta/threads/run.py:56-68]().

### Run Lifecycle State Machine

Runs progress through several statuses defined in `RunStatus` [src/openai/types/beta/threads/run.py:7]().

```mermaid
stateDiagram-v2
    [*] --> queued: Runs.create()
    queued --> in_progress: Processing
    in_progress --> requires_action: Tool call requested
    requires_action --> in_progress: Runs.submit_tool_outputs()
    in_progress --> completed: Success
    in_progress --> failed: Error
    in_progress --> incomplete: Token limit reached
    completed --> [*]
```

For details, see [Runs and Execution](#4.3.3).

**Sources**: [src/openai/resources/beta/threads/runs/runs.py:89-119](), [src/openai/types/beta/threads/run.py:107-197](), [src/openai/types/beta/threads/run.py:25-36]()

---

## Streaming

The SDK provides specialized handlers for streaming assistant events, allowing for real-time UI updates as the model generates content or calls tools. This is implemented via the `AssistantEventHandler` and `AssistantStreamManager` [src/openai/resources/beta/threads/runs/runs.py:35-42]().

```python
# Example logic based on resource methods
with client.beta.threads.runs.create(
    thread_id="thread_id",
    assistant_id="assistant_id",
    stream=True
) as stream:
    for event in stream:
        print(event)
```

For details, see [Streaming Assistant Events](#4.3.4).

**Sources**: [src/openai/resources/beta/threads/runs/runs.py:35-42](), [src/openai/resources/beta/threads/runs/runs.py:81-87]()

---

## Key Entities and Types

| Entity | Pydantic Model | Parameter Type (TypedDict) |
|--------|----------------|----------------------------|
| **Assistant** | `Assistant` [src/openai/types/beta/assistant.py:44]() | `AssistantCreateParams` [src/openai/types/beta/assistant_create_params.py:28]() |
| **Thread** | `Thread` [src/openai/types/beta/thread.py:49]() | `thread_create_params.ThreadCreateParams` [src/openai/resources/beta/threads/threads.py:36]() |
| **Run** | `Run` [src/openai/types/beta/threads/run.py:107]() | `RunCreateParamsBase` [src/openai/types/beta/threads/run_create_params.py:30]() |
| **Tool Resources** | `ToolResources` [src/openai/types/beta/assistant.py:33]() | `ToolResources` [src/openai/types/beta/assistant_create_params.py:103]() |

**Sources**: [src/openai/types/beta/assistant.py:44](), [src/openai/types/beta/thread.py:49](), [src/openai/types/beta/threads/run.py:107](), [src/openai/types/beta/assistant_create_params.py:28-103]()

---

# Page: Assistants and Configuration

# Assistants and Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/beta/assistants.py](src/openai/resources/beta/assistants.py)
- [src/openai/resources/beta/threads/runs/runs.py](src/openai/resources/beta/threads/runs/runs.py)
- [src/openai/resources/beta/threads/threads.py](src/openai/resources/beta/threads/threads.py)
- [src/openai/types/beta/assistant.py](src/openai/types/beta/assistant.py)
- [src/openai/types/beta/assistant_create_params.py](src/openai/types/beta/assistant_create_params.py)
- [src/openai/types/beta/assistant_update_params.py](src/openai/types/beta/assistant_update_params.py)
- [src/openai/types/beta/thread_create_and_run_params.py](src/openai/types/beta/thread_create_and_run_params.py)
- [src/openai/types/beta/threads/run.py](src/openai/types/beta/threads/run.py)
- [src/openai/types/beta/threads/run_create_params.py](src/openai/types/beta/threads/run_create_params.py)
- [src/openai/types/chat_model.py](src/openai/types/chat_model.py)
- [tests/api_resources/beta/test_assistants.py](tests/api_resources/beta/test_assistants.py)
- [tests/api_resources/beta/test_threads.py](tests/api_resources/beta/test_threads.py)
- [tests/api_resources/beta/threads/runs/test_steps.py](tests/api_resources/beta/threads/runs/test_steps.py)
- [tests/api_resources/beta/threads/test_messages.py](tests/api_resources/beta/threads/test_messages.py)
- [tests/api_resources/beta/threads/test_runs.py](tests/api_resources/beta/threads/test_runs.py)
- [tests/api_resources/fine_tuning/test_jobs.py](tests/api_resources/fine_tuning/test_jobs.py)
- [tests/api_resources/test_models.py](tests/api_resources/test_models.py)

</details>



This document covers the creation and configuration of Assistants in the OpenAI Python library. Assistants are stateful AI agents that can be configured with custom instructions, tools, and resources. For information about managing conversations with threads and messages, see [Threads and Messages](#4.3.2). For details on executing assistant runs, see [Runs and Execution](#4.3.3).

**Note**: The Assistants API is deprecated in favor of the Responses API. All methods in the Assistants API include deprecation warnings directing users to the newer Responses API [src/openai/resources/beta/assistants.py:57-57]().

## Overview

An Assistant represents a configured AI agent with specific behavior, capabilities, and resources. Assistants are created once and can be used across multiple conversation threads. The library provides methods for creating, updating, retrieving, listing, and deleting assistants through the `beta.assistants` resource [src/openai/resources/beta/assistants.py:35-35]().

## Assistant Object Structure

### Core Properties

The `Assistant` object returned by API operations is a Pydantic-based `BaseModel` containing the following properties:

| Property | Type | Description |
|----------|------|-------------|
| `id` | `str` | Unique identifier for the assistant |
| `object` | `Literal["assistant"]` | Object type, always "assistant" |
| `created_at` | `int` | Unix timestamp of creation |
| `name` | `Optional[str]` | Name (max 256 characters) |
| `description` | `Optional[str]` | Description (max 512 characters) |
| `model` | `str` | Model ID being used |
| `instructions` | `Optional[str]` | System instructions (max 256,000 characters) |
| `tools` | `List[AssistantTool]` | Enabled tools (max 128) |
| `tool_resources` | `Optional[ToolResources]` | Resources for tools |
| `metadata` | `Optional[Metadata]` | Custom key-value pairs (16 max) |
| `temperature` | `Optional[float]` | Sampling temperature (0-2) |
| `top_p` | `Optional[float]` | Nucleus sampling parameter |
| `response_format` | `Optional[AssistantResponseFormatOption]` | Output format specification |

**Sources**: [src/openai/types/beta/assistant.py:44-142]()

### Tool Resources Structure

Title: Assistant Tool Resource Mapping
```mermaid
graph TB
    Assistant["Assistant (src/openai/types/beta/assistant.py)"]
    ToolResources["ToolResources (BaseModel)"]
    CodeInterpreter["ToolResourcesCodeInterpreter"]
    FileSearch["ToolResourcesFileSearch"]
    
    Assistant --> ToolResources
    ToolResources --> CodeInterpreter
    ToolResources --> FileSearch
    
    CodeInterpreter --> FileIDs["file_ids: List[str]<br/>Max 20 files"]
    FileSearch --> VectorStoreIDs["vector_store_ids: List[str]<br/>Max 1 vector store"]
```

**Tool Resources Schema**

The `tool_resources` property provides resources specific to each tool type:

- **code_interpreter**: Requires `file_ids` - a list of up to 20 file IDs available to the code interpreter [src/openai/types/beta/assistant.py:14-21]().
- **file_search**: Requires `vector_store_ids` - a single vector store ID for search capabilities [src/openai/types/beta/assistant.py:23-31]().

**Sources**: [src/openai/types/beta/assistant.py:11-43]()

## Creating Assistants

### Basic Creation

The `create` method requires a `model` parameter. All other configuration is optional.

Title: Assistant Creation Data Flow
```mermaid
graph LR
    Client["client.beta.assistants (src/openai/resources/beta/assistants.py)"]
    Create["create()"]
    Params["AssistantCreateParams (TypedDict)"]
    Transform["maybe_transform() (src/openai/_utils.py)"]
    Post["POST /assistants"]
    Response["Assistant (src/openai/types/beta/assistant.py)"]
    
    Client --> Create
    Create --> Params
    Params --> Transform
    Transform --> Post
    Post --> Response
```

**Minimum Example Flow**: The simplest assistant creation requires specifying a model. The library transforms parameters using `maybe_transform` [src/openai/_utils.py:26-26]() and sends a POST request to `/assistants` with the `OpenAI-Beta: assistants=v2` header [src/openai/resources/beta/assistants.py:135-135]().

**Sources**: [src/openai/resources/beta/assistants.py:58-183](), [src/openai/_utils.py:26-26]()

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | `Union[str, ChatModel]` | Model ID or ChatModel constant |

**Sources**: [src/openai/types/beta/assistant_create_params.py:28-37]()

### Optional Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `Optional[str]` | `None` | Assistant name (max 256 chars) |
| `description` | `Optional[str]` | `None` | Description (max 512 chars) |
| `instructions` | `Optional[str]` | `None` | System instructions (max 256,000 chars) |
| `tools` | `Iterable[AssistantToolParam]` | `[]` | Enabled tools (max 128) |
| `tool_resources` | `Optional[ToolResources]` | `None` | Resources for tools |
| `metadata` | `Optional[Metadata]` | `None` | Custom key-value pairs |
| `temperature` | `Optional[float]` | Model default | Sampling temperature (0-2) |
| `top_p` | `Optional[float]` | Model default | Nucleus sampling |
| `response_format` | `Optional[AssistantResponseFormatOptionParam]` | `None` | Output format |
| `reasoning_effort` | `Optional[ReasoningEffort]` | Model default | Reasoning effort level |

**Sources**: [src/openai/types/beta/assistant_create_params.py:28-132](), [src/openai/resources/beta/assistants.py:58-183]()

### Reasoning Effort Configuration

For reasoning models, the `reasoning_effort` parameter constraints computational effort. Supported values are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max` [src/openai/types/beta/assistant_create_params.py:61-70]().

**Sources**: [src/openai/types/beta/assistant_create_params.py:61-70](), [src/openai/resources/beta/assistants.py:103-108]()

## Tool Configuration

### Available Tool Types

Title: Assistant Tool Hierarchy
```mermaid
graph TB
    Tools["Assistant Tools<br/>Max 128 per assistant"]
    
    CodeInterp["code_interpreter<br/>Execute Python code"]
    FileSearch["file_search<br/>Search vector stores"]
    Function["function<br/>Custom function calls"]
    
    Tools --> CodeInterp
    Tools --> FileSearch
    Tools --> Function
    
    CodeInterp -.requires.-> CodeRes["tool_resources.code_interpreter<br/>file_ids: max 20 files"]
    FileSearch -.requires.-> FSRes["tool_resources.file_search<br/>vector_store_ids: max 1 store"]
```

**Tool Types and Resources**: Each tool type requires specific resources configured via `tool_resources` [src/openai/types/beta/assistant_create_params.py:103-116]().

**Sources**: [src/openai/types/beta/assistant_create_params.py:103-116]()

### Tool Resources Configuration

#### Code Interpreter Resources

The `code_interpreter` tool resources contain a `file_ids` list with a maximum of 20 file IDs [src/openai/types/beta/assistant_create_params.py:128-134]().

**Sources**: [src/openai/types/beta/assistant_create_params.py:128-134]()

#### File Search Resources

The `file_search` tool resources can be configured using existing vector stores or by creating new ones with specific chunking strategies [src/openai/types/beta/assistant_create_params.py:174-188]().

#### Chunking Strategies

For new vector stores, chunking strategies control how files are split [src/openai/types/beta/assistant_create_params.py:137-171]():

| Strategy | Configuration | Description |
|----------|---------------|-------------|
| `auto` | `{"type": "auto"}` | Automatic chunking (800 token size, 400 overlap) |
| `static` | `{"type": "static", "static": {...}}` | Manual configuration |

**Static Chunking Parameters**:
- `max_chunk_size_tokens`: 100-4096 tokens (default 800) [src/openai/types/beta/assistant_create_params.py:154-160]().
- `chunk_overlap_tokens`: Overlap between chunks (default 400, max 50% of chunk size) [src/openai/types/beta/assistant_create_params.py:148-152]().

**Sources**: [src/openai/types/beta/assistant_create_params.py:137-171]()

## Response Format Configuration

The `response_format` parameter controls the assistant's output format [src/openai/types/beta/assistant_create_params.py:72-94]():

| Format Type | Configuration | Description |
|-------------|---------------|-------------|
| `json_object` | `{"type": "json_object"}` | Valid JSON output |
| `json_schema` | `{"type": "json_schema", "json_schema": {...}}` | Structured outputs matching schema |

**Compatibility**: Response format is compatible with GPT-4o, GPT-4 Turbo, and GPT-3.5 Turbo models since `gpt-3.5-turbo-1106` [src/openai/types/beta/assistant_create_params.py:75-77]().

**Sources**: [src/openai/types/beta/assistant_create_params.py:72-94]()

## Updating Assistants

### Update Method

The `update` method allows modifying any assistant property. Updates are sent as POST requests to `/assistants/{assistant_id}` [src/openai/resources/beta/assistants.py:219-399]().

Title: Assistant Update Lifecycle
```mermaid
sequenceDiagram
    participant Client as client.beta.assistants (src/openai/resources/beta/assistants.py)
    participant Update as update()
    participant Transform as maybe_transform()
    participant API as POST /assistants/{id}
    participant Response as Assistant
    
    Client->>Update: assistant_id, params
    Update->>Transform: AssistantUpdateParams (TypedDict)
    Transform->>API: Transformed body
    API->>Response: Updated assistant
    Response-->>Client: Assistant object
```

**Sources**: [src/openai/resources/beta/assistants.py:219-399]()

### Updatable Fields

Fields available in `AssistantUpdateParams` include [src/openai/types/beta/assistant_update_params.py:17-152]():

- `description`, `instructions`, `metadata`, `name`
- `reasoning_effort`, `response_format`, `temperature`
- `tool_resources`, `tools`, `top_p`, `model`

**Sources**: [src/openai/types/beta/assistant_update_params.py:17-152]()

## Additional Operations

### Retrieve Assistant

Retrieves an assistant by its ID.
**Sources**: [src/openai/resources/beta/assistants.py:185-217]()

### List Assistants

The `list` method returns a paginated cursor page of assistants [src/openai/resources/beta/assistants.py:401-464]().

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | `int` | Objects per page (1-100) |
| `order` | `Literal["asc", "desc"]` | Sort by `created_at` |

**Sources**: [src/openai/resources/beta/assistants.py:401-464]()

### Delete Assistant

Deletes an assistant and returns an `AssistantDeleted` confirmation object.
**Sources**: [src/openai/resources/beta/assistants.py:466-498]()

## Client Integration

### API Resource Hierarchy

Title: Assistants Resource Organization
```mermaid
graph TB
    Client["OpenAI Client (src/openai/_base_client.py)"]
    Beta["beta (src/openai/resources/beta/beta.py)"]
    Assistants["assistants (src/openai/resources/beta/assistants.py)"]
    
    Create["create()"]
    Retrieve["retrieve()"]
    Update["update()"]
    List["list()"]
    Delete["delete()"]
    
    WithRaw["with_raw_response"]
    WithStreaming["with_streaming_response"]
    
    Client --> Beta
    Beta --> Assistants
    
    Assistants --> Create
    Assistants --> Retrieve
    Assistants --> Update
    Assistants --> List
    Assistants --> Delete
    
    Assistants -.wrapper.-> WithRaw
    Assistants -.wrapper.-> WithStreaming
```

**Sources**: [src/openai/resources/beta/assistants.py:35-55]()

### Beta Header

All assistant API requests include the header `OpenAI-Beta: assistants=v2` [src/openai/resources/beta/assistants.py:135-135]().

**Sources**: [src/openai/resources/beta/assistants.py:135-135](), [src/openai/resources/beta/assistants.py:377-377]()

---

# Page: Threads and Messages

# Threads and Messages

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/beta/assistants.py](src/openai/resources/beta/assistants.py)
- [src/openai/resources/beta/threads/runs/runs.py](src/openai/resources/beta/threads/runs/runs.py)
- [src/openai/resources/beta/threads/threads.py](src/openai/resources/beta/threads/threads.py)
- [src/openai/types/beta/assistant.py](src/openai/types/beta/assistant.py)
- [src/openai/types/beta/assistant_create_params.py](src/openai/types/beta/assistant_create_params.py)
- [src/openai/types/beta/assistant_update_params.py](src/openai/types/beta/assistant_update_params.py)
- [src/openai/types/beta/thread_create_and_run_params.py](src/openai/types/beta/thread_create_and_run_params.py)
- [src/openai/types/beta/thread_create_params.py](src/openai/types/beta/thread_create_params.py)
- [src/openai/types/beta/threads/message.py](src/openai/types/beta/threads/message.py)
- [src/openai/types/beta/threads/message_create_params.py](src/openai/types/beta/threads/message_create_params.py)
- [src/openai/types/beta/threads/run.py](src/openai/types/beta/threads/run.py)
- [src/openai/types/beta/threads/run_create_params.py](src/openai/types/beta/threads/run_create_params.py)
- [src/openai/types/chat_model.py](src/openai/types/chat_model.py)

</details>



This page documents the Thread and Message management components of the Assistants API (Beta). Threads represent persistent conversation contexts that can be created, populated with messages, and executed by assistants through runs. Messages within threads capture the conversation history between users and assistants.

**Note:** The Assistants API is deprecated in favor of the Responses API [src/openai/resources/beta/threads/threads.py:94](). For information about assistant configuration and tools, see [Assistants and Configuration](#4.3.1). For information about executing assistants on threads, see [Runs and Execution](#4.3.3). For streaming assistant responses, see [Streaming Assistant Events](#4.3.4).

## Overview

A **thread** is a stateful conversation session that maintains:
- An ordered list of messages (user and assistant messages) [src/openai/types/beta/thread_create_params.py:31-35]()
- Tool resources (files for `code_interpreter`, vector stores for `file_search`) [src/openai/types/beta/thread_create_params.py:48-53]()
- Metadata for application-specific data storage [src/openai/types/beta/thread_create_params.py:37-45]()
- Association with runs that execute assistant logic on the thread's content [src/openai/resources/beta/threads/threads.py:66-68]()

Messages are the atomic units of conversation within threads, representing either user inputs or assistant responses [src/openai/types/beta/threads/message_create_params.py:19-26]().

### Thread and Message Architecture

```mermaid
graph TB
    subgraph "Client Access"
        Client["OpenAI/AsyncOpenAI Client"]
        BetaResource["client.beta"]
        ThreadsResource["client.beta.threads"]
        MessagesResource["client.beta.threads.messages"]
        RunsResource["client.beta.threads.runs"]
    end
    
    subgraph "Threads Resource"
        ThreadsClass["Threads (SyncAPIResource)"]
        CreateThread["create()"]
        RetrieveThread["retrieve(thread_id)"]
        UpdateThread["update(thread_id)"]
        DeleteThread["delete(thread_id)"]
        CreateAndRun["create_and_run()"]
    end
    
    subgraph "Messages Resource"
        MessagesClass["Messages (SyncAPIResource)"]
        CreateMessage["create(thread_id)"]
        ListMessages["list(thread_id)"]
        RetrieveMessage["retrieve(thread_id, message_id)"]
        UpdateMessage["update(thread_id, message_id)"]
        DeleteMessage["delete(thread_id, message_id)"]
    end
    
    subgraph "Data Types"
        Thread["Thread (BaseModel)"]
        ThreadParams["thread_create_params.ThreadCreateParams"]
        Message["Message (BaseModel)"]
        MessageParams["message_create_params"]
        ToolResources["ToolResources"]
    end
    
    Client --> BetaResource
    BetaResource --> ThreadsResource
    ThreadsResource --> ThreadsClass
    ThreadsResource --> MessagesResource
    ThreadsResource --> RunsResource
    
    ThreadsClass --> CreateThread
    ThreadsClass --> RetrieveThread
    ThreadsClass --> UpdateThread
    ThreadsClass --> DeleteThread
    ThreadsClass --> CreateAndRun
    
    MessagesResource --> MessagesClass
    MessagesClass --> CreateMessage
    MessagesClass --> ListMessages
    MessagesClass --> RetrieveMessage
    MessagesClass --> UpdateMessage
    MessagesClass --> DeleteMessage
    
    CreateThread --> Thread
    CreateThread --> ThreadParams
    CreateMessage --> Message
    CreateMessage --> MessageParams
    ThreadParams --> ToolResources
```

Sources: [src/openai/resources/beta/threads/threads.py:62-73](), [src/openai/resources/beta/threads/threads.py:13-30](), [src/openai/types/beta/thread.py](), [src/openai/types/beta/threads/message.py]()

## Thread Lifecycle Management

The `Threads` resource class provides full CRUD operations for thread management. All thread operations require the `OpenAI-Beta: assistants=v2` header [src/openai/resources/beta/threads/threads.py:135]().

### Creating Threads

Threads can be created empty or pre-populated with initial messages and tool resources.

**Method Signature:**
```python
client.beta.threads.create(
    messages: Iterable[thread_create_params.Message] | Omit = omit,
    metadata: Optional[Metadata] | Omit = omit,
    tool_resources: Optional[thread_create_params.ToolResources] | Omit = omit,
) -> Thread
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | `Iterable[Message]` | Initial messages to populate the thread with [src/openai/types/beta/thread_create_params.py:31-35]() |
| `metadata` | `Optional[Metadata]` | Set of 16 key-value pairs (max 64 char keys, 512 char values) [src/openai/types/beta/thread_create_params.py:37-45]() |
| `tool_resources` | `Optional[ToolResources]` | Resources for assistant tools (code_interpreter files, file_search vector stores) [src/openai/types/beta/thread_create_params.py:48-53]() |

Sources: [src/openai/resources/beta/threads/threads.py:95-154](), [src/openai/types/beta/thread_create_params.py:30-54]()

### Thread Creation Flow

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Threads as "Threads Resource"
    participant Transform as "maybe_transform()"
    participant BaseClient as "BaseClient._post()"
    participant API as "OpenAI API"
    
    User->>Threads: create(messages, tool_resources)
    Threads->>Transform: Transform params using<br/>ThreadCreateParams
    Transform-->>Threads: Transformed body
    Threads->>Threads: Add header:<br/>"OpenAI-Beta: assistants=v2"
    Threads->>BaseClient: POST /threads
    BaseClient->>API: HTTP POST request
    API-->>BaseClient: Thread response
    BaseClient->>BaseClient: Parse as Thread type
    BaseClient-->>User: Thread object
```

Sources: [src/openai/resources/beta/threads/threads.py:135-154]()

### Retrieving Threads

Fetch an existing thread by its ID using the `retrieve` method [src/openai/resources/beta/threads/threads.py:157-181]().

```python
thread = client.beta.threads.retrieve(thread_id="thread_abc123")
```

Sources: [src/openai/resources/beta/threads/threads.py:157-181]()

### Updating Threads

Modify thread metadata and tool resources using the `update` method [src/openai/resources/beta/threads/threads.py:183-237]().

**Updatable Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `metadata` | `Optional[Metadata]` | Application-specific key-value pairs [src/openai/types/beta/thread_update_params.py]() |
| `tool_resources` | `Optional[ToolResources]` | Update files/vector stores for tools [src/openai/types/beta/thread_update_params.py]() |

Sources: [src/openai/resources/beta/threads/threads.py:183-237]()

### Deleting Threads

Permanently remove a thread and all associated messages:

```python
deletion_status = client.beta.threads.delete(thread_id="thread_abc123")
# Returns ThreadDeleted with id, object="thread.deleted", deleted=True
```

Sources: [src/openai/resources/beta/threads/threads.py:239-272](), [src/openai/types/beta/thread_deleted.py]()

## Messages Sub-Resource

Messages are managed through the `client.beta.threads.messages` resource [src/openai/resources/beta/threads/threads.py:71-73](). Each message belongs to a specific thread and represents either user input or assistant output [src/openai/types/beta/threads/message_create_params.py:19-26]().

### Message Resource Access

```mermaid
graph LR
    Client["client.beta.threads"]
    Messages["messages property<br/>(cached_property)"]
    MessagesResource["Messages(SyncAPIResource)"]
    
    Client -->|"@cached_property"| Messages
    Messages --> MessagesResource
    
    subgraph "Message Operations"
        Create["create(thread_id, ...)"]
        List["list(thread_id)"]
        Retrieve["retrieve(thread_id, msg_id)"]
        Update["update(thread_id, msg_id)"]
        Delete["delete(thread_id, msg_id)"]
    end
    
    MessagesResource --> Create
    MessagesResource --> List
    MessagesResource --> Retrieve
    MessagesResource --> Update
    MessagesResource --> Delete
```

Sources: [src/openai/resources/beta/threads/threads.py:71-73](), [src/openai/resources/beta/threads/messages.py]()

### Message Structure

Messages support various content types, including text and multi-modal parts [src/openai/types/beta/threads/message_create_params.py:16-17]().

| Role | Description |
|--------------|-------------|
| `user` | Sent by an actual user [src/openai/types/beta/threads/message_create_params.py:21-23]() |
| `assistant` | Generated by the assistant [src/openai/types/beta/threads/message_create_params.py:24-25]() |

Messages also support **attachments** linking files to specific tools (`code_interpreter` or `file_search`) [src/openai/types/beta/threads/message_create_params.py:28-29]().

Sources: [src/openai/types/beta/threads/message_create_params.py:15-56]()

### Adding Messages to Threads

Messages are added via the `additional_messages` parameter in run creation [src/openai/types/beta/threads/run_create_params.py:57-58](), or directly through the Messages resource `create` method.

**Message Attachments:**

```python
class Attachment(TypedDict):
    file_id: str  # File ID to attach
    tools: Iterable[AttachmentTool]  # Tools to use this file with
```

Sources: [src/openai/types/beta/threads/message_create_params.py:50-55](), [src/openai/types/beta/threads/run_create_params.py:57-58]()

## Tool Resources Configuration

Threads and Assistants can be configured with tool-specific resources.

### Tool Resources Structure

```mermaid
graph TB
    ToolResources["ToolResources"]
    
    CodeInterpreter["code_interpreter"]
    FileSearch["file_search"]
    
    CodeInterpreterFiles["file_ids: List[str]<br/>(max 20 files)"]
    VectorStores["vector_store_ids: List[str]<br/>(max 1 vector store)"]
    
    ToolResources --> CodeInterpreter
    ToolResources --> FileSearch
    
    CodeInterpreter --> CodeInterpreterFiles
    FileSearch --> VectorStores
```

Sources: [src/openai/types/beta/thread_create_params.py:189-200](), [src/openai/types/beta/assistant.py:33-43]()

### Code Interpreter Resources

Files attached to `code_interpreter` are available for Python code execution within the assistant's sandbox environment. There can be a maximum of 20 files associated with the tool [src/openai/types/beta/thread_create_params.py:100-105]().

Sources: [src/openai/types/beta/thread_create_params.py:99-105]()

### File Search Resources

The `file_search` tool can be attached to vector stores [src/openai/types/beta/thread_create_params.py:171-178]().

**Chunking Strategies:**

| Strategy | Configuration |
|----------|---------------|
| `auto` | Default: 800 token chunks, 400 token overlap [src/openai/types/beta/thread_create_params.py:108-116]() |
| `static` | Custom: specify `max_chunk_size_tokens` and `chunk_overlap_tokens` [src/openai/types/beta/thread_create_params.py:118-131]() |

Sources: [src/openai/types/beta/thread_create_params.py:108-142]()

## Thread and Run Integration

### Create and Run Combined Operation

The `create_and_run` method creates a new thread and immediately starts a run on it in a single API call [src/openai/resources/beta/threads/threads.py:274-406]().

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Threads as "Threads Resource"
    participant API as "OpenAI API"
    
    User->>Threads: create_and_run(<br/>assistant_id,<br/>thread={messages, tool_resources},<br/>instructions, model, tools)
    
    Note over Threads: Combines thread creation<br/>and run initialization
    
    Threads->>API: POST /threads/runs
    
    alt Non-Streaming
        API-->>Threads: Run object
        Threads-->>User: Run (status: queued/in_progress)
    else Streaming
        API-->>Threads: Stream[AssistantStreamEvent]
        Threads-->>User: Stream of events
    end
```

Sources: [src/openai/resources/beta/threads/threads.py:274-406](), [src/openai/types/beta/thread_create_and_run_params.py:41-176]()

### Run Status and Execution

Runs represent the execution of an assistant on a thread. They transition through various statuses such as `queued`, `in_progress`, and `completed` [src/openai/types/beta/threads/run.py:107-113]().

| Field | Type | Description |
|-------|------|-------------|
| `usage` | `Usage` | Token statistics for the run [src/openai/types/beta/threads/run.py:91-105]() |
| `incomplete_details` | `IncompleteDetails` | Reason why a run might have stopped early [src/openai/types/beta/threads/run.py:25-37]() |
| `last_error` | `LastError` | Error information if the run failed [src/openai/types/beta/threads/run.py:39-47]() |

Sources: [src/openai/types/beta/threads/run.py:25-113]()

## Metadata Management

Both threads, messages, and runs support metadata for application-specific data storage [src/openai/types/beta/thread_create_params.py:37-45](), [src/openai/types/beta/threads/run_create_params.py:85-93]().

### Metadata Constraints

- **Limit**: Maximum 16 key-value pairs [src/openai/types/beta/thread_create_params.py:38]().
- **Key Length**: Maximum 64 characters [src/openai/types/beta/thread_create_params.py:43]().
- **Value Length**: Maximum 512 characters [src/openai/types/beta/thread_create_params.py:44]().

Sources: [src/openai/types/beta/thread_create_params.py:37-45](), [src/openai/types/beta/threads/run_create_params.py:85-93]()

## Truncation Strategies

When creating runs, threads can be truncated to fit within model context windows [src/openai/types/beta/threads/run.py:69-89]().

| Type | Behavior |
|------|----------|
| `auto` | Messages in the middle are dropped to fit `max_prompt_tokens` [src/openai/types/beta/threads/run.py:79-81]() |
| `last_messages` | The thread is truncated to the `n` most recent messages [src/openai/types/beta/threads/run.py:78-79]() |

Sources: [src/openai/types/beta/threads/run.py:69-89](), [src/openai/types/beta/threads/run_create_params.py:234-254]()

## Asynchronous Operations

All thread and message operations have async variants accessible through `AsyncThreads` [src/openai/resources/beta/threads/threads.py:705-1056]().

```python
async with AsyncOpenAI() as client:
    thread = await client.beta.threads.create(
        messages=[{"role": "user", "content": "Hello"}]
    )
```

Sources: [src/openai/resources/beta/threads/threads.py:705-1056]()

---

# Page: Runs and Execution

# Runs and Execution

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/beta/assistants.py](src/openai/resources/beta/assistants.py)
- [src/openai/resources/beta/threads/messages.py](src/openai/resources/beta/threads/messages.py)
- [src/openai/resources/beta/threads/runs/runs.py](src/openai/resources/beta/threads/runs/runs.py)
- [src/openai/resources/beta/threads/runs/steps.py](src/openai/resources/beta/threads/runs/steps.py)
- [src/openai/resources/beta/threads/threads.py](src/openai/resources/beta/threads/threads.py)
- [src/openai/resources/fine_tuning/jobs/jobs.py](src/openai/resources/fine_tuning/jobs/jobs.py)
- [src/openai/resources/models.py](src/openai/resources/models.py)
- [src/openai/types/beta/assistant.py](src/openai/types/beta/assistant.py)
- [src/openai/types/beta/assistant_create_params.py](src/openai/types/beta/assistant_create_params.py)
- [src/openai/types/beta/assistant_update_params.py](src/openai/types/beta/assistant_update_params.py)
- [src/openai/types/beta/thread_create_and_run_params.py](src/openai/types/beta/thread_create_and_run_params.py)
- [src/openai/types/beta/threads/run.py](src/openai/types/beta/threads/run.py)
- [src/openai/types/beta/threads/run_create_params.py](src/openai/types/beta/threads/run_create_params.py)
- [src/openai/types/chat_model.py](src/openai/types/chat_model.py)
- [src/openai/types/fine_tuning/fine_tuning_job.py](src/openai/types/fine_tuning/fine_tuning_job.py)
- [src/openai/types/fine_tuning/job_create_params.py](src/openai/types/fine_tuning/job_create_params.py)
- [src/openai/types/fine_tuning/job_list_params.py](src/openai/types/fine_tuning/job_list_params.py)

</details>



This document describes the run lifecycle and execution system in the Assistants API. A run represents the execution of an assistant on a thread, processing messages and generating responses while potentially calling tools. For information about creating and configuring assistants, see [4.3.1](). For information about threads and messages, see [4.3.2](). For information about streaming run events, see [4.3.4]().

**Deprecation Notice**: The Assistants API is deprecated in favor of the Responses API. All methods in the runs resource are marked with deprecation warnings [src/openai/resources/beta/threads/runs/runs.py:90-91]().

## Run Lifecycle and State Machine

A run progresses through a series of statuses from creation to completion. Understanding this state machine is critical for properly handling run execution.

Title: Assistant Run State Machine
```mermaid
stateDiagram-v2
    [*] --> "queued": "create()"
    "queued" --> "in_progress": "Processing begins"
    "in_progress" --> "requires_action": "Tool calls needed"
    "in_progress" --> "completed": "Success"
    "in_progress" --> "failed": "Error occurred"
    "in_progress" --> "incomplete": "Token limit reached"
    "in_progress" --> "cancelling": "cancel() called"
    
    "requires_action" --> "in_progress": "submit_tool_outputs()"
    "requires_action" --> "expired": "Timeout (10 min)"
    
    "cancelling" --> "cancelled": "Cancellation complete"
    
    "completed" --> [*]
    "failed" --> [*]
    "cancelled" --> [*]
    "incomplete" --> [*]
    "expired" --> [*]
```

**Terminal States**: `completed`, `failed`, `cancelled`, `incomplete`, `expired` [src/openai/types/beta/threads/run.py:225-230]().  
**Action Required State**: `requires_action` - run pauses waiting for tool output submission [src/openai/types/beta/threads/run.py:192-196]().  
**Processing States**: `queued`, `in_progress`, `cancelling` [src/openai/types/beta/threads/run.py:225-230]().

Sources: [src/openai/types/beta/threads/run.py:107-274](), [src/openai/types/beta/threads/run_status.py]()

## Core Run Classes

The runs system is implemented through resource classes and type models that work together to manage run execution.

Title: Natural Language to Code Entity Space - Runs
```mermaid
graph TB
    subgraph "Resource Layer (Code Entity Space)"
        Runs["Runs Resource<br/>src/openai/resources/beta/threads/runs/runs.py"]
        AsyncRuns["AsyncRuns Resource<br/>src/openai/resources/beta/threads/runs/runs.py"]
    end
    
    subgraph "Data Models (Code Entity Space)"
        Run["Run Model<br/>src/openai/types/beta/threads/run.py"]
        RunCreateParams["RunCreateParams<br/>src/openai/types/beta/threads/run_create_params.py"]
        RunStatus["RunStatus<br/>src/openai/types/beta/threads/run_status.py"]
    end
    
    subgraph "Execution Flow (Natural Language Space)"
        Create["'Create a Run'"]
        CheckStatus["'Check if finished'"]
        SubmitTools["'Submit Tool Results'"]
    end
    
    Create --> Runs
    Runs -->|"returns"| Run
    RunCreateParams -.->|"defines"| Create
    CheckStatus --> Run
    Run -->|"has"| RunStatus
    SubmitTools --> Runs
    Runs -->|"submit_tool_outputs()"| Run
```

**Key Classes**:
- `Runs` / `AsyncRuns` at [src/openai/resources/beta/threads/runs/runs.py:62-59]() - Resource classes providing methods for run operations.
- `Run` at [src/openai/types/beta/threads/run.py:107-108]() - Pydantic model representing a run execution.
- `RunCreateParamsBase` at [src/openai/types/beta/threads/run_create_params.py:30-31]() - TypedDict for create parameters.

Sources: [src/openai/resources/beta/threads/runs/runs.py:1-59](), [src/openai/types/beta/threads/run.py:1-274]()

## Creating Runs

### Basic Run Creation

The simplest way to create a run is to specify the assistant ID and thread ID:

```python
run = client.beta.threads.runs.create(
    thread_id="thread_abc123",
    assistant_id="asst_xyz789"
)
```

This creates a run with the assistant's default configuration. The synchronous method implementation is at [src/openai/resources/beta/threads/runs/runs.py:91-119]().

Sources: [src/openai/resources/beta/threads/runs/runs.py:91-119]()

### Run Configuration Options

Runs support extensive configuration options that override assistant defaults:

| Parameter | Type | Description |
|-----------|------|-------------|
| `assistant_id` | `str` | Required. Assistant to execute [src/openai/types/beta/threads/run_create_params.py:31]() |
| `instructions` | `str` | Override assistant instructions [src/openai/types/beta/threads/run_create_params.py:60]() |
| `additional_instructions` | `str` | Append to assistant instructions [src/openai/types/beta/threads/run_create_params.py:50]() |
| `additional_messages` | `Iterable[AdditionalMessage]` | Add messages before running [src/openai/types/beta/threads/run_create_params.py:57]() |
| `model` | `Union[str, ChatModel]` | Override assistant model [src/openai/types/beta/threads/run_create_params.py:95]() |
| `tools` | `Iterable[AssistantToolParam]` | Override assistant tools [src/openai/types/beta/threads/run_create_params.py:163]() |
| `tool_choice` | `AssistantToolChoiceOptionParam` | Control tool behavior [src/openai/types/beta/threads/run_create_params.py:152]() |
| `parallel_tool_calls` | `bool` | Enable parallel function calling [src/openai/types/beta/threads/run_create_params.py:103]() |
| `reasoning_effort` | `ReasoningEffort` | Constrain reasoning for reasoning models [src/openai/types/beta/threads/run_create_params.py:110]() |
| `response_format` | `AssistantResponseFormatOptionParam` | Specify output format [src/openai/types/beta/threads/run_create_params.py:121]() |
| `temperature` | `float` | Sampling temperature (0-2) [src/openai/types/beta/threads/run_create_params.py:145]() |
| `top_p` | `float` | Nucleus sampling parameter [src/openai/types/beta/threads/run_create_params.py:169]() |
| `max_prompt_tokens` | `int` | Maximum prompt tokens across turns [src/openai/types/beta/threads/run_create_params.py:76]() |
| `max_completion_tokens` | `int` | Maximum completion tokens across turns [src/openai/types/beta/threads/run_create_params.py:67]() |
| `truncation_strategy` | `TruncationStrategy` | Control context window truncation [src/openai/types/beta/threads/run_create_params.py:170]() |

Sources: [src/openai/types/beta/threads/run_create_params.py:30-189](), [src/openai/resources/beta/threads/runs/runs.py:91-119]()

## Handling Required Actions

When a run enters `requires_action` status, the assistant has made tool calls that require external execution.

Title: Tool Call Execution Flow
```mermaid
sequenceDiagram
    participant App as Python Application
    participant Runs as Runs Resource<br/>(runs.py)
    participant API as OpenAI API
    
    App->>Runs: create(assistant_id, thread_id)
    Runs->>API: POST /threads/{id}/runs
    API-->>App: Run (status: in_progress)
    
    Note over API: Model determines tool call needed
    
    API-->>App: Run (status: requires_action)
    
    Note over App: App checks run.required_action.submit_tool_outputs.tool_calls
    
    App->>Runs: submit_tool_outputs(tool_outputs)
    Runs->>API: POST /threads/{id}/runs/{id}/submit_tool_outputs
    API-->>App: Run (status: in_progress)
```

### Submitting Tool Outputs

The `submit_tool_outputs()` method provides the results of tool execution back to the run [src/openai/resources/beta/threads/runs/runs.py:1146-1215]().

```python
run = client.beta.threads.runs.submit_tool_outputs(
    thread_id="thread_abc123",
    run_id="run_xyz789",
    tool_outputs=[
        {
            "tool_call_id": "call_123",
            "output": "28 degrees"
        }
    ]
)
```

The `RequiredAction` structure contains the specific tool calls generated by the model [src/openai/types/beta/threads/run.py:49-67]().

Sources: [src/openai/types/beta/threads/run.py:49-67](), [src/openai/resources/beta/threads/runs/runs.py:1146-1215]()

## Run Management Operations

### Retrieving and Listing Runs

- **Retrieve**: Fetch the current state of a specific run [src/openai/resources/beta/threads/runs/runs.py:961-997]().
- **List**: Retrieve all runs for a thread, supporting cursor-based pagination [src/openai/resources/beta/threads/runs/runs.py:1046-1114]().

```python
# List runs with pagination
runs = client.beta.threads.runs.list(thread_id="thread_123", limit=10)
for run in runs:
    print(run.id, run.status)
```

Sources: [src/openai/resources/beta/threads/runs/runs.py:961-1114]()

### Canceling Runs

An in-progress run can be canceled using the `cancel` method [src/openai/resources/beta/threads/runs/runs.py:1116-1144](). This transitions the run to the `cancelling` state.

Sources: [src/openai/resources/beta/threads/runs/runs.py:1116-1144]()

## Thread Creation with Run

The `create_and_run` method on the `Threads` resource combines thread creation and run execution into a single API call [src/openai/resources/beta/threads/threads.py:274-361]().

```python
run = client.beta.threads.create_and_run(
    assistant_id="asst_123",
    thread={
        "messages": [{"role": "user", "content": "Explain quantum physics"}]
    }
)
```

This uses the `ThreadCreateAndRunParams` structure [src/openai/types/beta/thread_create_and_run_params.py:41-175]().

Sources: [src/openai/resources/beta/threads/threads.py:274-361](), [src/openai/types/beta/thread_create_and_run_params.py:41-175]()

## Token Management and Usage

The `Run` object tracks token consumption in the `usage` field [src/openai/types/beta/threads/run.py:91-105]().

```python
class Usage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
```

If a run exceeds `max_prompt_tokens` or `max_completion_tokens`, it enters the `incomplete` state [src/openai/types/beta/threads/run.py:137-141](). Details on which limit was hit are stored in `incomplete_details` [src/openai/types/beta/threads/run.py:25-37]().

Sources: [src/openai/types/beta/threads/run.py:25-141]()

---

# Page: Streaming Assistant Events

# Streaming Assistant Events

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/lib/streaming/_assistants.py](src/openai/lib/streaming/_assistants.py)
- [tests/lib/test_assistants.py](tests/lib/test_assistants.py)

</details>



This page documents the streaming event system for the Assistants API, which allows processing incremental responses from assistant runs. When creating a run with `stream=True`, the API returns a stream of `AssistantStreamEvent` objects that can be processed using the `AssistantEventHandler` pattern.

For information about creating and managing assistants, see [Assistants and Configuration](#4.3.1). For details on the run lifecycle without streaming, see [Runs and Execution](#4.3.3).

## Overview

The Assistants API supports streaming responses during run execution. Instead of waiting for the entire run to complete, the stream provides real-time events as the assistant processes messages, uses tools, and generates responses. The SDK provides handler classes that process these events and maintain accumulated state.

**Key Components:**
- `Stream[AssistantStreamEvent]` / `AsyncStream[AssistantStreamEvent]` - The core interface to iterate over SSE responses [src/openai/_streaming.py:12-12]().
- `AssistantEventHandler` / `AsyncAssistantEventHandler` - Handler classes with callback methods and snapshot management [src/openai/lib/streaming/_assistants.py:31-56](), [src/openai/lib/streaming/_assistants.py:475-504]().
- `AssistantStreamManager` / `AsyncAssistantStreamManager` - Context managers for stream lifecycle [src/openai/lib/streaming/_assistants.py:439-440](), [src/openai/lib/streaming/_assistants.py:857-858]().

Sources: [src/openai/_streaming.py:12-12](), [src/openai/lib/streaming/_assistants.py:31-858](), [src/openai/types/beta/assistant_stream_event.py:1-100]()

## Creating Streaming Runs

Streaming is enabled by setting `stream=True` when creating a run. The SDK provides method overloads that return `Stream[AssistantStreamEvent]` when streaming is enabled.

| Method | Streaming Return Type |
|--------|---------------------|
| `client.beta.threads.runs.create(..., stream=True)` | `Stream[AssistantStreamEvent]` |
| `client.beta.threads.create_and_run(..., stream=True)` | `Stream[AssistantStreamEvent]` |

**Natural Language to Code Entity Mapping**

```mermaid
graph TB
    subgraph "Natural Language Space"
        RUN_START["Start Streaming Run"]
        PROC_EVENT["Process Event"]
        COLL_SNAP["Collect Snapshot"]
    end
    
    subgraph "Code Entity Space"
        CREATE_RUN["client.beta.threads.runs.create()"]
        EVENT_HANDLER["AssistantEventHandler"]
        SNAPSHOT["current_message_snapshot"]
        TEXT_DELTA["text_deltas"]
    end
    
    RUN_START -.-> CREATE_RUN
    PROC_EVENT -.-> EVENT_HANDLER
    PROC_EVENT -.-> TEXT_DELTA
    COLL_SNAP -.-> SNAPSHOT
```

Sources: [tests/lib/test_assistants.py:21-39](), [src/openai/lib/streaming/_assistants.py:31-133]()

## AssistantStreamEvent Types

The `AssistantStreamEvent` discriminated union contains multiple event types that represent different stages of run execution. Each event has an `event` field (discriminator) and a `data` field with the event payload [src/openai/types/beta/assistant_stream_event.py:1-100]().

### Event Categories

| Event Pattern | Description | Data Type |
|--------------|-------------|-----------|
| `thread.run.*` | Run lifecycle events | `Run` |
| `thread.message.*` | Message creation and updates | `Message` or `MessageDelta` |
| `thread.run.step.*` | Run step execution | `RunStep` or `RunStepDelta` |
| `thread.created` | Thread creation | `Thread` |
| `error` | Error events | `Error` |

### Run Lifecycle Events

```mermaid
stateDiagram-v2
    [*] --> thread.run.created
    thread.run.created --> thread.run.queued
    thread.run.queued --> thread.run.in_progress
    thread.run.in_progress --> thread.run.step.created
    thread.run.step.created --> thread.run.step.in_progress
    thread.run.step.in_progress --> thread.run.step.delta
    thread.run.step.delta --> thread.run.step.delta: tool call deltas
    thread.run.step.delta --> thread.run.step.completed
    thread.run.step.completed --> thread.message.created
    thread.message.created --> thread.message.delta
    thread.message.delta --> thread.message.delta: content deltas
    thread.message.delta --> thread.message.completed
    thread.message.completed --> thread.run.completed
    thread.run.completed --> [*]
    
    thread.run.in_progress --> thread.run.requires_action
    thread.run.requires_action --> [*]
    thread.run.in_progress --> thread.run.failed
    thread.run.failed --> [*]
```

Sources: [src/openai/lib/streaming/_assistants.py:270-411](), [src/openai/types/beta/assistant_stream_event.py:1-100]()

## AssistantEventHandler Pattern

The `AssistantEventHandler` class provides a structured way to process streaming events through callback methods. Users subclass the handler and override methods for events they want to process.

### Handler Structure

```mermaid
classDiagram
    class AssistantEventHandler {
        +text_deltas: Iterator[str]
        +current_event: AssistantStreamEvent
        +current_run: Run
        +current_message_snapshot: Message
        +on_event(event)
        +on_text_delta(delta, snapshot)
        +on_message_created(message)
        +on_run_step_delta(delta, snapshot)
        +until_done()
        +get_final_run() Run
    }
    
    class AsyncAssistantEventHandler {
        +text_deltas: AsyncIterator[str]
        +on_event(event) async
        +on_text_delta(delta, snapshot) async
        +until_done() async
    }
```

Sources: [src/openai/lib/streaming/_assistants.py:31-434](), [src/openai/lib/streaming/_assistants.py:475-853]()

### Callback Methods

The handler provides callback methods for different event types. Each callback receives structured data specific to that event.

| Callback | Triggered By | Arguments |
|----------|-------------|-----------|
| `on_event(event)` | Every event | Full `AssistantStreamEvent` [src/openai/lib/streaming/_assistants.py:153-154]() |
| `on_text_created(text)` | New text content block | `Text` object [src/openai/lib/streaming/_assistants.py:220-221]() |
| `on_text_delta(delta, snapshot)` | Text content update | `TextDelta`, accumulated `Text` [src/openai/lib/streaming/_assistants.py:223-224]() |
| `on_message_created(message)` | New message | `Message` object [src/openai/lib/streaming/_assistants.py:216-217]() |
| `on_message_delta(delta, snapshot)` | Message update | `MessageDelta`, accumulated `Message` [src/openai/lib/streaming/_assistants.py:218-219]() |
| `on_run_step_delta(delta, snapshot)` | Run step update | `RunStepDelta`, accumulated `RunStep` [src/openai/lib/streaming/_assistants.py:159-160]() |
| `on_tool_call_delta(delta, snapshot)` | Tool call update | `ToolCallDelta`, accumulated `ToolCall` [src/openai/lib/streaming/_assistants.py:192-193]() |
| `on_exception(exception)` | Any exception | `Exception` object [src/openai/lib/streaming/_assistants.py:198-199]() |
| `on_end()` | Stream complete | None [src/openai/lib/streaming/_assistants.py:146-151]() |

Sources: [src/openai/lib/streaming/_assistants.py:146-268]()

## Event Accumulation and Snapshots

The handler automatically accumulates delta events into complete snapshots. This is crucial for understanding the current state without manually tracking deltas.

### Delta vs Snapshot Pattern

```mermaid
sequenceDiagram
    participant API as OpenAI API
    participant Handler as AssistantEventHandler
    participant User as User Callback
    
    API->>Handler: thread.message.delta (delta="Hello")
    Handler->>Handler: Accumulate into snapshot
    Handler->>User: on_text_delta(delta, snapshot="Hello")
    
    API->>Handler: thread.message.delta (delta=" world")
    Handler->>Handler: Accumulate into snapshot
    Handler->>User: on_text_delta(delta, snapshot="Hello world")
```

The accumulation logic is implemented in the internal `__stream__` method [src/openai/lib/streaming/_assistants.py:270](), which routes events to `accumulate_event()` [src/openai/lib/streaming/_assistants.py:888]() to merge delta payloads into progressively complete objects.

**Accumulated State:**
- `current_message_snapshot`: Latest complete `Message` object [src/openai/lib/streaming/_assistants.py:92-93]().
- `current_run_step_snapshot`: Latest complete `RunStep` object [src/openai/lib/streaming/_assistants.py:85-89]().
- `get_final_messages()`: Returns the full list of accumulated `Message` snapshots [src/openai/lib/streaming/_assistants.py:126-133]().

Sources: [src/openai/lib/streaming/_assistants.py:76-93](), [src/openai/lib/streaming/_assistants.py:270-413]()

## Using the Stream Manager

The `AssistantStreamManager` provides a context manager pattern for handling stream lifecycle. It ensures proper initialization and cleanup of the underlying HTTP connection.

### Implementation Logic

```mermaid
graph TB
    subgraph "Stream Lifecycle"
        START["Manager __enter__"]
        INIT["Handler _init(stream)"]
        LOOP["Stream Iterator"]
        EMIT["__stream__()"]
        DONE["Manager __exit__"]
        CLOSE["stream.close()"]
    end
    
    subgraph "Entity Mapping"
        MANAGER["AssistantStreamManager"]
        HANDLER["AssistantEventHandler"]
        SSE["AssistantStreamEvent"]
    end
    
    START --> INIT
    INIT --> LOOP
    LOOP --> EMIT
    EMIT --> SSE
    SSE --> LOOP
    LOOP --> DONE
    DONE --> CLOSE
    
    MANAGER --- START
    HANDLER --- EMIT
```

Sources: [src/openai/lib/streaming/_assistants.py:439-473](), [src/openai/lib/streaming/_assistants.py:857-885]()

## Text Delta Iterator

The `text_deltas` property provides a convenient iterator over just the text content, skipping other event types like run step updates or tool calls.

```python
# Usage Example
for text in handler.text_deltas:
    print(text, end="", flush=True)
```

This iterator filters for `thread.message.delta` events and yields `content_delta.text.value` for every text fragment [src/openai/lib/streaming/_assistants.py:135-142]().

Sources: [src/openai/lib/streaming/_assistants.py:32-43](), [src/openai/lib/streaming/_assistants.py:135-143]()

## Helper Methods

The handler provides methods to wait for completion and retrieve final results:

| Method | Description | Return Type |
|--------|-------------|-------------|
| `until_done()` | Consume stream until complete. | `None` [src/openai/lib/streaming/_assistants.py:104-106]() |
| `get_final_run()` | Wait and return final `Run` object. | `Run` [src/openai/lib/streaming/_assistants.py:108-115]() |
| `get_final_messages()` | Wait and return all `Message` snapshots. | `list[Message]` [src/openai/lib/streaming/_assistants.py:126-133]() |
| `get_final_run_steps()` | Wait and return all `RunStep` snapshots. | `list[RunStep]` [src/openai/lib/streaming/_assistants.py:117-124]() |

These methods call `consume_sync_iterator` (or `consume_async_iterator` for async) internally to ensure the stream is fully processed before returning [src/openai/lib/streaming/_assistants.py:8-8]().

Sources: [src/openai/lib/streaming/_assistants.py:104-133](), [src/openai/_utils.py:8-8]()

## Error Handling

The handler provides callbacks for error scenarios. If an exception occurs during iteration, the `on_exception` method is triggered [src/openai/lib/streaming/_assistants.py:421-422]().

### Timeout Handling

If an `httpx.TimeoutException` or `asyncio.TimeoutError` occurs:
1. `on_timeout()` callback is called [src/openai/lib/streaming/_assistants.py:419-420]().
2. `on_exception(exception)` is called [src/openai/lib/streaming/_assistants.py:421-422]().
3. The exception is re-raised to the caller [src/openai/lib/streaming/_assistants.py:423-423]().

Sources: [src/openai/lib/streaming/_assistants.py:415-434](), [src/openai/lib/streaming/_assistants.py:833-853]()

---

# Page: Fine-Tuning API

# Fine-Tuning API

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/beta/threads/messages.py](src/openai/resources/beta/threads/messages.py)
- [src/openai/resources/beta/threads/runs/steps.py](src/openai/resources/beta/threads/runs/steps.py)
- [src/openai/resources/evals/evals.py](src/openai/resources/evals/evals.py)
- [src/openai/resources/evals/runs/runs.py](src/openai/resources/evals/runs/runs.py)
- [src/openai/resources/fine_tuning/checkpoints/permissions.py](src/openai/resources/fine_tuning/checkpoints/permissions.py)
- [src/openai/resources/fine_tuning/jobs/jobs.py](src/openai/resources/fine_tuning/jobs/jobs.py)
- [src/openai/resources/models.py](src/openai/resources/models.py)
- [src/openai/resources/vector_stores/vector_stores.py](src/openai/resources/vector_stores/vector_stores.py)
- [src/openai/types/fine_tuning/checkpoints/permission_retrieve_response.py](src/openai/types/fine_tuning/checkpoints/permission_retrieve_response.py)
- [src/openai/types/fine_tuning/fine_tuning_job.py](src/openai/types/fine_tuning/fine_tuning_job.py)
- [src/openai/types/fine_tuning/job_create_params.py](src/openai/types/fine_tuning/job_create_params.py)
- [src/openai/types/fine_tuning/job_list_params.py](src/openai/types/fine_tuning/job_list_params.py)
- [tests/api_resources/fine_tuning/checkpoints/test_permissions.py](tests/api_resources/fine_tuning/checkpoints/test_permissions.py)

</details>



The Fine-Tuning API provides functionality for training custom models on domain-specific data using supervised learning, Direct Preference Optimization (DPO), or reinforcement learning methods. This API enables creating fine-tuning jobs, monitoring training progress through events, managing checkpoints, and controlling access permissions for fine-tuned models.

For information about file uploads for training data, see [File Management and Uploads](#4.6). For details about the base client infrastructure used by this API, see [Core Client Classes](#3).

## Resource Hierarchy and Structure

The Fine-Tuning API is organized into a nested resource hierarchy accessible from the main client. The structure reflects distinct functional areas: job management, checkpoint access, and permission control.

Title: Fine-Tuning Resource Hierarchy
```mermaid
graph TB
    subgraph "Client Entry Points"
        CLIENT["OpenAI.fine_tuning"]
        ASYNC_CLIENT["AsyncOpenAI.fine_tuning"]
    end
    
    subgraph "Jobs Resource [Jobs]"
        JOBS["Jobs (src/openai/resources/fine_tuning/jobs/jobs.py)"]
        JOB_CREATE["create()"]
        JOB_RETRIEVE["retrieve(fine_tuning_job_id)"]
        JOB_LIST["list()"]
        JOB_CANCEL["cancel(fine_tuning_job_id)"]
        JOB_LIST_EVENTS["list_events(fine_tuning_job_id)"]
        
        JOBS_CHECKPOINTS["jobs.checkpoints (Checkpoints)"]
        JOB_CHECKPOINT_LIST["list(fine_tuning_job_id)"]
    end
    
    subgraph "Checkpoints Resource [Checkpoints]"
        CHECKPOINTS["Checkpoints (src/openai/resources/fine_tuning/checkpoints/checkpoints.py)"]
        CHECKPOINT_PERMISSIONS["permissions (Permissions)"]
        PERM_CREATE["create(fine_tuned_model_checkpoint)"]
        PERM_RETRIEVE["retrieve(fine_tuned_model_checkpoint)"]
        PERM_LIST["list(fine_tuned_model_checkpoint)"]
    end
    
    CLIENT --> JOBS
    CLIENT --> CHECKPOINTS
    
    JOBS --> JOB_CREATE
    JOBS --> JOB_RETRIEVE
    JOBS --> JOB_LIST
    JOBS --> JOB_CANCEL
    JOBS --> JOB_LIST_EVENTS
    
    JOBS --> JOBS_CHECKPOINTS
    JOBS_CHECKPOINTS --> JOB_CHECKPOINT_LIST
    
    CHECKPOINTS --> CHECKPOINT_PERMISSIONS
    CHECKPOINT_PERMISSIONS --> PERM_CREATE
    CHECKPOINT_PERMISSIONS --> PERM_RETRIEVE
    CHECKPOINT_PERMISSIONS --> PERM_LIST
```

**Resource Paths and Endpoints**

| Resource Path | HTTP Endpoint | Purpose |
|--------------|---------------|---------|
| `client.fine_tuning.jobs` | `/fine_tuning/jobs` | Create and manage fine-tuning jobs [src/openai/resources/fine_tuning/jobs/jobs.py:37-38]() |
| `client.fine_tuning.jobs.checkpoints` | `/fine_tuning/jobs/{job_id}/checkpoints` | List checkpoints for a specific job [src/openai/resources/fine_tuning/jobs/jobs.py:41-43]() |
| `client.fine_tuning.checkpoints.permissions` | `/fine_tuning/checkpoints/{checkpoint}/permissions` | Manage access permissions for model checkpoints [src/openai/resources/fine_tuning/checkpoints/permissions.py:31-32]() |

Sources: [src/openai/resources/fine_tuning/jobs/jobs.py:1-43](), [src/openai/resources/fine_tuning/checkpoints/permissions.py:1-32]()

## Fine-Tuning Jobs

Fine-tuning jobs represent training operations that customize a base model using provided training data. Jobs support multiple training methods and can be monitored or cancelled during execution.

### Job Lifecycle States

The `FineTuningJob` object represents the state of a training operation [src/openai/types/fine_tuning/fine_tuning_job.py:76-79]().

Title: Fine-Tuning Job State Machine
```mermaid
stateDiagram-v2
    [*] --> created: "Jobs.create()"
    created --> validating_files: "System starts validation"
    validating_files --> queued: "Files validated"
    queued --> running: "Resources allocated"
    validating_files --> failed: "Validation error"
    running --> succeeded: "Training completes"
    running --> failed: "Training error"
    running --> cancelled: "Jobs.cancel()"
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
```

**Job State Descriptions**

| State | Description |
|-------|-------------|
| `validating_files` | Training and validation files are being validated [src/openai/types/fine_tuning/fine_tuning_job.py:133-134]() |
| `queued` | Job is waiting for compute resources [src/openai/types/fine_tuning/fine_tuning_job.py:130-131]() |
| `running` | Model training is in progress [src/openai/types/fine_tuning/fine_tuning_job.py:130-131]() |
| `succeeded` | Training completed successfully, fine-tuned model is available [src/openai/types/fine_tuning/fine_tuning_job.py:130-131]() |
| `failed` | Job failed; check `error` field for details [src/openai/types/fine_tuning/fine_tuning_job.py:87-91]() |
| `cancelled` | Job was manually cancelled [src/openai/types/fine_tuning/fine_tuning_job.py:130-131]() |

Sources: [src/openai/types/fine_tuning/fine_tuning_job.py:76-134]()

### Creating Fine-Tuning Jobs

Jobs are created through `client.fine_tuning.jobs.create()` [src/openai/resources/fine_tuning/jobs/jobs.py:64-82]().

```python
# Example supervised fine-tuning job creation
job = client.fine_tuning.jobs.create(
    model="gpt-4o-mini",
    training_file="file-123",
    method={
        "type": "supervised",
        "supervised": {
            "hyperparameters": {
                "n_epochs": 3
            }
        }
    }
)
```

**Core Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model` | `str` | Yes | Base model to fine-tune (e.g., `gpt-4o-mini`) [src/openai/resources/fine_tuning/jobs/jobs.py:67]() |
| `training_file` | `str` | Yes | File ID containing training examples [src/openai/resources/fine_tuning/jobs/jobs.py:68]() |
| `validation_file` | `str` | No | File ID for validation data [src/openai/resources/fine_tuning/jobs/jobs.py:75]() |
| `method` | `Method` | No | Training method configuration [src/openai/resources/fine_tuning/jobs/jobs.py:72]() |
| `suffix` | `str` | No | String suffix for the fine-tuned model name [src/openai/resources/fine_tuning/jobs/jobs.py:74]() |
| `seed` | `int` | No | Seed for reproducibility [src/openai/resources/fine_tuning/jobs/jobs.py:73]() |
| `integrations` | `Iterable[Integration]` | No | List of integrations (e.g., Weights & Biases) [src/openai/resources/fine_tuning/jobs/jobs.py:70]() |

Sources: [src/openai/resources/fine_tuning/jobs/jobs.py:64-160](), [src/openai/types/fine_tuning/fine_tuning_job.py:60-75](), [src/openai/types/fine_tuning/job_create_params.py:128-176]()

### Job Management Operations

| Method | Returns | Description |
|--------|---------|-------------|
| `create()` | `FineTuningJob` | Create a new fine-tuning job [src/openai/resources/fine_tuning/jobs/jobs.py:64-160]() |
| `retrieve(job_id)` | `FineTuningJob` | Get details of a specific job [src/openai/resources/fine_tuning/jobs/jobs.py:192-212]() |
| `list()` | `SyncCursorPage[FineTuningJob]` | List all fine-tuning jobs [src/openai/resources/fine_tuning/jobs/jobs.py:236-264]() |
| `cancel(job_id)` | `FineTuningJob` | Cancel a running job [src/openai/resources/fine_tuning/jobs/jobs.py:288-308]() |
| `list_events(job_id)` | `SyncCursorPage[FineTuningJobEvent]` | List events for a specific job [src/openai/resources/fine_tuning/jobs/jobs.py:332-365]() |

Sources: [src/openai/resources/fine_tuning/jobs/jobs.py:64-365]()

## Training Methods and Hyperparameters

The SDK supports multiple training methods defined in `openai.types.fine_tuning.fine_tuning_job.Method` [src/openai/types/fine_tuning/fine_tuning_job.py:60-75]().

### Supervised Fine-Tuning

Supervised fine-tuning is the standard method for customizing models on input-output pairs.

**Hyperparameters** [src/openai/types/fine_tuning/fine_tuning_job.py:34-58]()

| Parameter | Type | Description |
|-----------|------|-------------|
| `batch_size` | `int \| "auto"` | Number of examples in each batch [src/openai/types/fine_tuning/fine_tuning_job.py:40-45]() |
| `learning_rate_multiplier` | `float \| "auto"` | Scaling factor for the learning rate [src/openai/types/fine_tuning/fine_tuning_job.py:47-51]() |
| `n_epochs` | `int \| "auto"` | Number of cycles through the training dataset [src/openai/types/fine_tuning/fine_tuning_job.py:53-57]() |

### Advanced Methods (DPO and Reinforcement)

In addition to `supervised`, the API supports `dpo` (Direct Preference Optimization) and `reinforcement` learning methods [src/openai/types/fine_tuning/fine_tuning_job.py:63-75](). These are configured via the `method` parameter in `Jobs.create()` [src/openai/resources/fine_tuning/jobs/jobs.py:72]().

Sources: [src/openai/types/fine_tuning/fine_tuning_job.py:34-75](), [src/openai/types/fine_tuning/job_create_params.py:177-191]()

## Checkpoints and Permissions

Checkpoints are intermediate model states saved during training. Access to these checkpoints can be shared across projects within an organization.

### Listing Checkpoints

Checkpoints are retrieved for a specific job via `client.fine_tuning.jobs.checkpoints.list(job_id)` [src/openai/resources/fine_tuning/jobs/jobs.py:41-43]().

### Checkpoint Permissions

Permissions allow organization owners to share fine-tuned model checkpoints with other projects. **Note:** Calling these endpoints requires an Admin API Key [src/openai/resources/fine_tuning/checkpoints/permissions.py:66-67]().

Title: Permission Creation Request Data Flow
```mermaid
graph LR
    subgraph "Permission Request Flow"
        REQ["Permissions.create()"]
        TRANSFORM["maybe_transform()"]
        CLIENT["BaseClient._post()"]
        API["POST /fine_tuning/checkpoints/{id}/permissions"]
    end
    
    REQ --> TRANSFORM
    TRANSFORM --> CLIENT
    CLIENT --> API
```

**Permission Operations** [src/openai/resources/fine_tuning/checkpoints/permissions.py:31-240]()

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `create()` | `checkpoint_id`, `project_ids` | `SyncPage[PermissionCreateResponse]` | Grant access to specific projects [src/openai/resources/fine_tuning/checkpoints/permissions.py:53-102]() |
| `list()` | `checkpoint_id` | `SyncConversationCursorPage[PermissionListResponse]` | List all permissions for a checkpoint [src/openai/resources/fine_tuning/checkpoints/permissions.py:192-240]() |
| `retrieve()` | `checkpoint_id` | `PermissionRetrieveResponse` | **Deprecated:** Use `list()` instead [src/openai/resources/fine_tuning/checkpoints/permissions.py:104-105]() |

Sources: [src/openai/resources/fine_tuning/checkpoints/permissions.py:31-240](), [tests/api_resources/fine_tuning/checkpoints/test_permissions.py:25-46](), [src/openai/types/fine_tuning/checkpoints/permission_retrieve_response.py:29-39]()

## Summary of Data Flow

The following diagram illustrates the data flow from client request to the fine-tuning training infrastructure.

Title: Fine-Tuning Job Creation Sequence
```mermaid
sequenceDiagram
    participant App as "Application Code"
    participant SDK as "OpenAI Python SDK"
    participant FT as "Fine-Tuning Resource (Jobs)"
    participant API as "OpenAI API Endpoints"

    App->>SDK: "client.fine_tuning.jobs.create(model, training_file)"
    SDK->>FT: "Jobs.create()"
    FT->>FT: "maybe_transform(body, JobCreateParams)"
    FT->>API: "POST /v1/fine_tuning/jobs"
    API-->>FT: "FineTuningJob (JSON)"
    FT-->>SDK: "FineTuningJob (Pydantic Model)"
    SDK-->>App: "FineTuningJob instance"
```

Sources: [src/openai/resources/fine_tuning/jobs/jobs.py:64-160](), [src/openai/types/fine_tuning/fine_tuning_job.py:76-177]()

---

# Page: Embeddings and Vector Stores

# Embeddings and Vector Stores

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/embeddings.py](src/openai/resources/embeddings.py)
- [src/openai/resources/vector_stores/file_batches.py](src/openai/resources/vector_stores/file_batches.py)
- [src/openai/resources/vector_stores/files.py](src/openai/resources/vector_stores/files.py)
- [src/openai/types/embedding_create_params.py](src/openai/types/embedding_create_params.py)
- [src/openai/types/responses/file_search_tool.py](src/openai/types/responses/file_search_tool.py)
- [src/openai/types/responses/file_search_tool_param.py](src/openai/types/responses/file_search_tool_param.py)
- [src/openai/types/vector_stores/file_batch_create_params.py](src/openai/types/vector_stores/file_batch_create_params.py)
- [src/openai/types/vector_stores/file_create_params.py](src/openai/types/vector_stores/file_create_params.py)
- [tests/api_resources/vector_stores/test_file_batches.py](tests/api_resources/vector_stores/test_file_batches.py)
- [tests/api_resources/vector_stores/test_files.py](tests/api_resources/vector_stores/test_files.py)

</details>



**Purpose**: This page documents the embeddings API for generating vector representations of text and the vector stores API for managing searchable collections of embedded content. These APIs enable semantic search and retrieval-augmented generation (RAG) workflows.

For information about using vector stores with the Assistants API, see [Assistants API (Beta)](#4.3). For file upload mechanics, see [File Management and Uploads](#4.6).

---

## System Overview

The embeddings and vector stores subsystem provides two complementary capabilities:

1. **Embeddings API**: Converts text into high-dimensional vector representations that capture semantic meaning.
2. **Vector Stores API**: Manages collections of embedded content with built-in semantic search, file chunking, and batch operations.

### Resource Hierarchy

```mermaid
graph TB
    subgraph "Client Layer"
        CLIENT["OpenAI client / AsyncOpenAI client"]
    end
    
    subgraph "Resource Classes"
        EMBED["Embeddings resource<br/>src/openai/resources/embeddings.py"]
        VECTOR["VectorStores resource<br/>src/openai/resources/vector_stores/vector_stores.py"]
        FILES["Files subresource<br/>src/openai/resources/vector_stores/files.py"]
        BATCHES["FileBatches subresource<br/>src/openai/resources/vector_stores/file_batches.py"]
    end
    
    subgraph "HTTP Endpoints"
        EMBED_EP["POST /embeddings"]
        VS_EP["POST /vector_stores"]
        FILE_EP["POST /vector_stores/{vs_id}/files"]
        BATCH_EP["POST /vector_stores/{vs_id}/file_batches"]
    end
    
    subgraph "Response Types"
        EMBED_RESP["CreateEmbeddingResponse<br/>src/openai/types/create_embedding_response.py"]
        VS_RESP["VectorStore<br/>src/openai/types/vector_store.py"]
        FILE_RESP["VectorStoreFile<br/>src/openai/types/vector_stores/vector_store_file.py"]
        BATCH_RESP["VectorStoreFileBatch<br/>src/openai/types/vector_stores/vector_store_file_batch.py"]
    end
    
    CLIENT --> EMBED
    CLIENT --> VECTOR
    VECTOR --> FILES
    VECTOR --> BATCHES
    
    EMBED --> EMBED_EP
    VECTOR --> VS_EP
    FILES --> FILE_EP
    BATCHES --> BATCH_EP
    
    EMBED_EP --> EMBED_RESP
    VS_EP --> VS_RESP
    FILE_EP --> FILE_RESP
    BATCH_EP --> BATCH_RESP
```

**Sources**: [src/openai/resources/embeddings.py:27-151](), [src/openai/resources/vector_stores/files.py:28-48](), [src/openai/resources/vector_stores/file_batches.py:31-51]()

---

## Embeddings API

The `Embeddings` resource generates vector representations from text inputs. These vectors encode semantic meaning in a high-dimensional space where similar content has nearby vectors.

### Implementation Detail: Base64 Optimization
The SDK includes a performance optimization for embeddings. By default, if a user does not specify an `encoding_format`, the SDK requests `base64` from the API to reduce payload size [src/openai/resources/embeddings.py:111-112](). It then uses a `post_parser` to decode this back into a list of floats [src/openai/resources/embeddings.py:114-134](). If `numpy` is available, it uses `np.frombuffer` for high-speed conversion; otherwise, it falls back to the standard library `array.array` [src/openai/resources/embeddings.py:126-132]().

**Sources**: [src/openai/resources/embeddings.py:111-134]()

### Request Parameters

The `create` method accepts `EmbeddingCreateParams`:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | `str | SequenceNotStr[str] | Iterable[int] | Iterable[Iterable[int]]` | Yes | Input text to embed, encoded as a string or array of tokens. [src/openai/types/embedding_create_params.py:15-26]() |
| `model` | `str | EmbeddingModel` | Yes | ID of the model to use (e.g., `text-embedding-3-small`). [src/openai/types/embedding_create_params.py:28-36]() |
| `dimensions` | `int` | No | Number of dimensions for the output vector (supported in v3 models). [src/openai/types/embedding_create_params.py:38-42]() |
| `encoding_format` | `"float" | "base64"` | No | Format for the returned embeddings. [src/openai/types/embedding_create_params.py:44-48]() |

**Sources**: [src/openai/resources/embeddings.py:51-65](), [src/openai/types/embedding_create_params.py:14-56]()

---

## Vector Store Management

Vector stores provide persistent storage for embedded content with automatic indexing. The `client.vector_stores` resource manages these collections, while sub-resources handle file ingestion.

### File Management (`vector_stores.files`)

The `Files` sub-resource allows attaching individual files to a vector store. It supports standard CRUD operations and convenience polling methods.

**Key Methods**:
- `create`: Attaches an existing `File` ID to a vector store. [src/openai/resources/vector_stores/files.py:48-112]()
- `list`: Lists files attached to a store, returning a `SyncCursorPage[VectorStoreFile]`. [src/openai/resources/vector_stores/files.py:180-213]()
- `poll`: A helper that waits until a file's processing status is terminal (`completed` or `failed`).

**Sources**: [src/openai/resources/vector_stores/files.py:28-213](), [tests/api_resources/vector_stores/test_files.py:27-185]()

### Batch Ingestion (`vector_stores.file_batches`)

For multi-file ingestion, `FileBatches` is recommended to reduce write request pressure. It supports up to 2000 files per batch [src/openai/types/vector_stores/file_batch_create_params.py:38-39]().

```mermaid
sequenceDiagram
    participant App as "Application Code"
    participant SDK as "FileBatches Resource"
    participant API as "OpenAI API (v2 Beta)"

    App->>SDK: create(vector_store_id="vs_123", file_ids=["file_1", "file_2"])
    Note over SDK: Uses file_batch_create_params.FileBatchCreateParams
    SDK->>API: POST /vector_stores/vs_123/file_batches (Headers: OpenAI-Beta=assistants=v2)
    API-->>SDK: VectorStoreFileBatch (status="in_progress")
    SDK-->>App: batch_object
    
    App->>SDK: poll(batch_id="vsfb_123", vector_store_id="vs_123")
    loop Every few seconds
        SDK->>API: GET /vector_stores/vs_123/file_batches/vsfb_123
        API-->>SDK: status="in_progress"
    end
    API-->>SDK: status="completed"
    SDK-->>App: final_batch_object
```

**Sources**: [src/openai/resources/vector_stores/file_batches.py:51-123](), [src/openai/types/vector_stores/file_batch_create_params.py:31-49]()

---

## File Chunking Strategies

When files are added to a vector store, they are partitioned into chunks for indexing. The SDK supports configuring these strategies via `FileChunkingStrategyParam`.

| Strategy | Type | Description |
|----------|------|-------------|
| **Auto** | `auto` | Default strategy. The system automatically determines chunk boundaries. [src/openai/types/vector_stores/file_create_params.py:33-37]() |
| **Static** | `static` | Allows manual control over chunking parameters. [src/openai/types/vector_stores/file_create_params.py:33-37]() |

**Sources**: [src/openai/types/vector_stores/file_create_params.py:32-37](), [src/openai/types/vector_stores/file_batch_create_params.py:24-29]()

---

## Semantic Search Configuration

While vector stores are often used implicitly by Assistants, they can be configured for specific search behaviors via the `FileSearchToolParam`.

### Ranking and Hybrid Search
The `RankingOptions` allow fine-tuning how results are retrieved, including support for hybrid search (balancing semantic matches vs. keyword matches).

- `ranker`: Can be `auto` or a specific version like `default-2024-11-15`. [src/openai/types/responses/file_search_tool_param.py:38-39]()
- `score_threshold`: A value between 0 and 1 to filter out irrelevant results. [src/openai/types/responses/file_search_tool_param.py:41-47]()
- `hybrid_search`: Configures `embedding_weight` and `text_weight` for reciprocal rank fusion. [src/openai/types/responses/file_search_tool_param.py:17-27]()

**Sources**: [src/openai/types/responses/file_search_tool_param.py:12-72](), [src/openai/types/responses/file_search_tool.py:15-69]()

---

# Page: File Management and Uploads

# File Management and Uploads

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_files.py](src/openai/_files.py)
- [src/openai/resources/audio/speech.py](src/openai/resources/audio/speech.py)
- [src/openai/resources/audio/transcriptions.py](src/openai/resources/audio/transcriptions.py)
- [src/openai/resources/audio/translations.py](src/openai/resources/audio/translations.py)
- [src/openai/resources/completions.py](src/openai/resources/completions.py)
- [src/openai/resources/files.py](src/openai/resources/files.py)
- [src/openai/resources/moderations.py](src/openai/resources/moderations.py)
- [src/openai/resources/uploads/uploads.py](src/openai/resources/uploads/uploads.py)
- [src/openai/types/audio/speech_create_params.py](src/openai/types/audio/speech_create_params.py)
- [src/openai/types/beta/threads/run_submit_tool_outputs_params.py](src/openai/types/beta/threads/run_submit_tool_outputs_params.py)
- [src/openai/types/completion_create_params.py](src/openai/types/completion_create_params.py)
- [src/openai/types/file_create_params.py](src/openai/types/file_create_params.py)
- [src/openai/types/file_object.py](src/openai/types/file_object.py)
- [src/openai/types/file_purpose.py](src/openai/types/file_purpose.py)
- [src/openai/types/realtime/conversation_item_create_event.py](src/openai/types/realtime/conversation_item_create_event.py)
- [src/openai/types/realtime/conversation_item_create_event_param.py](src/openai/types/realtime/conversation_item_create_event_param.py)
- [src/openai/types/upload_create_params.py](src/openai/types/upload_create_params.py)

</details>



## Purpose and Scope

This document covers the file management capabilities of the OpenAI Python library, including file upload, retrieval, deletion, content access, and multipart uploads for large files. Files in the OpenAI API serve as inputs to various endpoints including Assistants, Fine-tuning, Batch processing, and Vector Stores.

For information about vector store-specific file operations and chunking strategies, see [Embeddings and Vector Stores](#4.5). For technical details about file extraction and transformation mechanisms, see [File Extraction and Processing](#6.5).

---

## File Resource Architecture

The Files resource is implemented in the `Files` class and `AsyncFiles` class, providing both synchronous and asynchronous interfaces for file operations. All file operations return `FileObject` instances containing metadata about uploaded files.

### Core File Operations

Detailed Mapping of Code Entities:
- **Client Classes**: `Files` [src/openai/resources/files.py:36](), `AsyncFiles` [src/openai/resources/files.py:383]().
- **Response Models**: `FileObject` [src/openai/types/file_object.py:11](), `FileDeleted` [src/openai/types/file_deleted.py:11]().
- **Parameter Types**: `FileCreateParams` [src/openai/types/file_create_params.py:13](), `FilePurpose` [src/openai/types/file_purpose.py:8]().

```mermaid
graph TB
    subgraph "Client Layer"
        SyncFiles["Files<br/>(SyncAPIResource)"]
        AsyncFiles["AsyncFiles<br/>(AsyncAPIResource)"]
    end
    
    subgraph "File Operations"
        Create["create()<br/>Upload file"]
        Retrieve["retrieve()<br/>Get file metadata"]
        List["list()<br/>List files"]
        Delete["delete()<br/>Remove file"]
        Content["content()<br/>Get raw content"]
        Wait["wait_for_processing()<br/>Poll until ready"]
    end
    
    subgraph "Response Types"
        FileObject["FileObject<br/>id, filename, purpose, status"]
        FileDeleted["FileDeleted<br/>id, deleted"]
        BinaryContent["HttpxBinaryResponseContent<br/>Raw file bytes"]
        FilePage["SyncCursorPage[FileObject]<br/>Paginated results"]
    end
    
    subgraph "Parameter Types"
        FileTypes["FileTypes<br/>file, bytes, Path"]
        FilePurpose["FilePurpose<br/>assistants, batch, fine-tune, etc."]
        ExpiresAfter["ExpiresAfter<br/>anchor, seconds"]
    end
    
    SyncFiles --> Create
    SyncFiles --> Retrieve
    SyncFiles --> List
    SyncFiles --> Delete
    SyncFiles --> Content
    SyncFiles --> Wait
    
    Create --> FileObject
    Retrieve --> FileObject
    List --> FilePage
    Delete --> FileDeleted
    Content --> BinaryContent
    Wait --> FileObject
    
    FileTypes -.input.-> Create
    FilePurpose -.input.-> Create
    ExpiresAfter -.input.-> Create
```

**Sources:** [src/openai/resources/files.py:36-349](), [src/openai/types/file_object.py:11-61](), [src/openai/types/file_create_params.py:13-52]()

---

## Basic File Operations

### Creating Files

Files are uploaded using the `create()` method with a required `purpose` parameter that determines how the file can be used across different endpoints. The SDK uses `extract_files` [src/openai/_utils.py:16]() to pull file data from the request body and `deepcopy_with_paths` [src/openai/_files.py:128]() to prevent mutation of the original input.

```mermaid
sequenceDiagram
    participant User as User Code
    participant Files as Files Resource
    participant Extract as extract_files()
    participant Transform as maybe_transform()
    participant HTTP as BaseClient._post()
    participant API as OpenAI API
    
    User->>Files: create(file=..., purpose="assistants")
    Files->>Files: deepcopy_with_paths(body, [["file"]])
    Files->>Extract: extract_files(body, paths=[["file"]])
    Extract-->>Files: (files_dict)
    Files->>Transform: maybe_transform(body, FileCreateParams)
    Transform-->>Files: API-compatible params
    
    Note over Files: Set Content-Type: multipart/form-data
    
    Files->>HTTP: _post("/files", body, files)
    HTTP->>API: POST /files
    API-->>HTTP: FileObject JSON
    HTTP-->>Files: Parsed FileObject
    Files-->>User: FileObject(id, filename, status, ...)
```

**Implementation:** [src/openai/resources/files.py:60-152]()

**Parameters:**
- `file: FileTypes` - The file object to upload (can be a file handle, bytes, or `pathlib.Path`) [src/openai/types/file_create_params.py:14-15]()
- `purpose: FilePurpose` - Required purpose identifier [src/openai/types/file_create_params.py:17-26]()
- `expires_after: ExpiresAfter | Omit` - Optional expiration policy [src/openai/types/file_create_params.py:28-33]()

**File Purposes:**

| Purpose | Use Case | Size Limit | Format Requirements |
|---------|----------|------------|---------------------|
| `assistants` | Assistants API tools | 512 MB per file | Up to 2M tokens, specific types |
| `batch` | Batch API requests | 200 MB | `.jsonl` with specific format |
| `fine-tune` | Fine-tuning models | 512 MB | `.jsonl` with chat/completions format |
| `vision` | Vision fine-tuning | 512 MB | Images |
| `user_data` | General purpose | 512 MB | Any format |
| `evals` | Evaluation datasets | 512 MB | Eval data sets |

**Sources:** [src/openai/resources/files.py:73-126](), [src/openai/types/file_create_params.py:17-26](), [src/openai/_files.py:128-173]()

### Retrieving File Metadata

The `retrieve()` method returns metadata about a specific file without downloading its content.

```python
# Synchronous
file = client.files.retrieve(file_id="file-abc123")
# Returns: FileObject(id="file-abc123", filename="data.jsonl", status="processed", ...)
```

**Sources:** [src/openai/resources/files.py:154-186]()

### Listing Files

The `list()` method returns a paginated collection of files with optional filtering by purpose. It uses the `SyncCursorPage` [src/openai/pagination.py:144]() for synchronous iteration.

```python
# List all files
page = client.files.list()

# Filter by purpose and control pagination
page = client.files.list(
    purpose="assistants",
    limit=20,
    order="desc"
)

# Iterate through all pages
for file in page.auto_paging_iter():
    print(f"{file.filename}: {file.status}")
```

**Sources:** [src/openai/resources/files.py:188-249]()

### Deleting Files

The `delete()` method removes a file from the account.

```python
deletion_status = client.files.delete(file_id="file-abc123")
# Returns: FileDeleted(id="file-abc123", deleted=True)
```

**Sources:** [src/openai/resources/files.py:251-282]()

---

## File Content Access

### Retrieving File Content

The `content()` method is used for accessing raw file contents.

1. **`content()`** - Returns raw binary content as `HttpxBinaryResponseContent`.
2. **`retrieve_content()`** - Deprecated method that returns content as string.

```python
# Preferred method - returns binary content
binary_content = client.files.content(file_id="file-abc123")
# Can write to file: binary_content.write_to_file("output.jsonl")
```

**Implementation Details:**
The `content()` method sets the `Accept: application/binary` header and returns the response without parsing, allowing efficient handling of large files. [src/openai/resources/files.py:313]()

**Sources:** [src/openai/resources/files.py:284-317](), [src/openai/resources/files.py:319-352]()

---

## File Processing and Status Tracking

### File Status Lifecycle

Files transition through several states after upload. Terminal states are `processed`, `error`, and `uploaded` (initial). These are defined in the `FileObject` model [src/openai/types/file_object.py:45-50]().

```mermaid
stateDiagram-v2
    [*] --> uploaded: create()
    uploaded --> processing: API begins processing
    processing --> processed: Success
    processing --> error: Processing failed
    processed --> deleted: delete()
    error --> deleted: delete()
    deleted --> [*]
```

**Sources:** [src/openai/types/file_object.py:45-50]()

### wait_for_processing() Helper

The `wait_for_processing()` helper method polls the file status until it reaches a terminal state. It implements a basic polling loop using `time.sleep` [src/openai/resources/files.py:373]().

```python
file = client.files.create(
    file=open("dataset.jsonl", "rb"),
    purpose="fine-tune"
)

# Wait until processing completes (default 30 min timeout)
processed_file = client.files.wait_for_processing(
    id=file.id,
    poll_interval=5.0
)
```

**Sources:** [src/openai/resources/files.py:354-375]()

---

## Multipart Uploads for Large Files

For files larger than 512 MB, the Uploads API provides multipart capabilities. Currently, an Upload can accept at most 8 GB in total and expires after an hour [src/openai/resources/uploads/uploads.py:188-189]().

### Multipart Upload Architecture

The `Uploads` resource manages the session, while the `Parts` sub-resource handles individual chunk uploads.

```mermaid
graph TB
    subgraph "Uploads Resource"
        Uploads["Uploads<br/>(SyncAPIResource)"]
        UploadCreate["create()<br/>Initialize upload"]
        UploadComplete["complete()<br/>Finalize upload"]
        UploadChunked["upload_file_chunked()<br/>Convenience wrapper"]
    end
    
    subgraph "Parts Sub-Resource"
        Parts["Parts<br/>(SyncAPIResource)"]
        PartCreate["create()<br/>Upload chunk"]
    end
    
    subgraph "Upload Types"
        UploadObject["Upload<br/>id, status, file, expires_at"]
    end
    
    Uploads --> UploadCreate
    Uploads --> UploadComplete
    Uploads --> UploadChunked
    Uploads --> Parts
    Parts --> PartCreate
    
    UploadCreate --> UploadObject
    UploadComplete --> UploadObject
```

**Sources:** [src/openai/resources/uploads/uploads.py:43-166](), [src/openai/resources/uploads/parts.py:33-113]()

### Multipart Upload Workflow

The `upload_file_chunked()` method [src/openai/resources/uploads/uploads.py:97]() provides a high-level wrapper that manages the lifecycle of a multipart upload, splitting the file into parts (defaulting to 64MB via `DEFAULT_PART_SIZE`) [src/openai/resources/uploads/uploads.py:38]().

```mermaid
sequenceDiagram
    participant User
    participant Uploads as Uploads.upload_file_chunked
    participant Parts as Parts.create
    participant API as OpenAI API
    
    User->>Uploads: upload_file_chunked(file, mime_type, purpose)
    Uploads->>API: POST /uploads (Initialize)
    API-->>Uploads: Upload(id)
    
    loop For each 64MB part
        Uploads->>Parts: create(upload_id, data)
        Parts->>API: POST /uploads/{id}/parts
        API-->>Parts: UploadPart(id)
    end
    
    Uploads->>API: POST /uploads/{id}/complete
    API-->>Uploads: Upload(status="completed")
    Uploads-->>User: Upload object
```

**Sources:** [src/openai/resources/uploads/uploads.py:108-166]()

---

## Audio and Transcription Files

The Audio API handles files for transcription, translation, and speech generation. These methods utilize the same `extract_files` logic to handle multipart form data.

| Resource | Method | Input/Output | Notes |
|----------|--------|--------------|-------|
| `audio.transcriptions` | `create()` | `FileTypes` -> `Transcription` | Supports flac, mp3, mp4, wav, etc. [src/openai/resources/audio/transcriptions.py:97]() |
| `audio.translations` | `create()` | `FileTypes` -> `Translation` | Translates audio into English [src/openai/resources/audio/translations.py:119]() |
| `audio.speech` | `create()` | `input: str` -> `BinaryContent` | Generates audio from text [src/openai/resources/audio/speech.py:68]() |

**Sources:** [src/openai/resources/audio/transcriptions.py:68-152](), [src/openai/resources/audio/translations.py:103-164](), [src/openai/resources/audio/speech.py:50-129]()

---

## Integration and Expiration

### Expiration Configuration

Files can be configured with an `ExpiresAfter` policy during creation. This policy defines an `anchor` (currently only `created_at`) and `seconds` (between 3600 and 2592000) [src/openai/types/file_create_params.py:36-52]().

```python
from openai.types.file_create_params import ExpiresAfter

file = client.files.create(
    file=open("temp.jsonl", "rb"),
    purpose="user_data",
    expires_after=ExpiresAfter(
        anchor="created_at",
        seconds=3600  # 1 hour
    )
)
```

**Sources:** [src/openai/types/file_create_params.py:36-52]()

### Multi-Modal Moderation

The Moderations API also supports multi-modal inputs, allowing for image-based moderation by providing a list of `ModerationMultiModalInputParam` [src/openai/resources/moderations.py:51]().

```python
client.moderations.create(
    input=[
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,..."}
        }
    ]
)
```

**Sources:** [src/openai/resources/moderations.py:48-99]()

---

# Page: Audio, Images, and Video APIs

# Audio, Images, and Video APIs

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/image_stream.py](examples/image_stream.py)
- [src/openai/lib/streaming/responses/_events.py](src/openai/lib/streaming/responses/_events.py)
- [src/openai/resources/audio/speech.py](src/openai/resources/audio/speech.py)
- [src/openai/resources/audio/transcriptions.py](src/openai/resources/audio/transcriptions.py)
- [src/openai/resources/audio/translations.py](src/openai/resources/audio/translations.py)
- [src/openai/resources/completions.py](src/openai/resources/completions.py)
- [src/openai/resources/containers/files/files.py](src/openai/resources/containers/files/files.py)
- [src/openai/resources/files.py](src/openai/resources/files.py)
- [src/openai/resources/images.py](src/openai/resources/images.py)
- [src/openai/resources/moderations.py](src/openai/resources/moderations.py)
- [src/openai/resources/skills/skills.py](src/openai/resources/skills/skills.py)
- [src/openai/resources/skills/versions/versions.py](src/openai/resources/skills/versions/versions.py)
- [src/openai/resources/uploads/parts.py](src/openai/resources/uploads/parts.py)
- [src/openai/resources/videos.py](src/openai/resources/videos.py)
- [src/openai/types/audio/speech_create_params.py](src/openai/types/audio/speech_create_params.py)
- [src/openai/types/audio/transcription_create_params.py](src/openai/types/audio/transcription_create_params.py)
- [src/openai/types/audio/translation_create_params.py](src/openai/types/audio/translation_create_params.py)
- [src/openai/types/beta/threads/run_submit_tool_outputs_params.py](src/openai/types/beta/threads/run_submit_tool_outputs_params.py)
- [src/openai/types/completion_create_params.py](src/openai/types/completion_create_params.py)
- [src/openai/types/image_edit_params.py](src/openai/types/image_edit_params.py)
- [src/openai/types/image_edit_partial_image_event.py](src/openai/types/image_edit_partial_image_event.py)
- [src/openai/types/image_edit_stream_event.py](src/openai/types/image_edit_stream_event.py)
- [src/openai/types/image_generate_params.py](src/openai/types/image_generate_params.py)
- [src/openai/types/responses/response_function_shell_tool_call_output.py](src/openai/types/responses/response_function_shell_tool_call_output.py)
- [src/openai/types/responses/tool.py](src/openai/types/responses/tool.py)
- [src/openai/types/responses/tool_param.py](src/openai/types/responses/tool_param.py)
- [src/openai/types/video_create_params.py](src/openai/types/video_create_params.py)
- [tests/api_resources/test_images.py](tests/api_resources/test_images.py)
- [tests/api_resources/test_videos.py](tests/api_resources/test_videos.py)

</details>



This page documents the OpenAI client library's support for non-text modalities: audio processing (transcriptions, translations, and speech synthesis), image generation and editing, and video generation. These APIs enable applications to work with multimedia content beyond text-based interactions.

For multi-modal inputs within conversational contexts (e.g., images in chat messages), see the Responses API documentation ([Responses API](#4.2)) and Chat Completions API documentation ([Chat Completions API](#4.1)). For file management infrastructure used by these APIs, see [File Management and Uploads](#4.6).

---

## Overview of Media API Resources

The client exposes three primary resource namespaces for media operations:

| Resource | Client Property | Purpose |
|----------|----------------|---------|
| Audio | `client.audio` | Transcribe/translate audio to text, synthesize speech from text |
| Images | `client.images` | Generate, edit, and create variations of images |
| Video | `client.videos` | Generate, edit, and remix video content |

Sources: [src/openai/resources/audio/transcriptions.py:45-46](), [src/openai/resources/images.py:28-29](), [src/openai/resources/videos.py:49-50]()

---

## Audio APIs

The `audio` resource provides sub-resources for audio processing. All audio APIs accept file inputs or text inputs and return structured responses or binary content.

### Audio Resource Structure

```mermaid
graph TB
    Client["OpenAI / AsyncOpenAI"]
    AudioResource["client.audio<br/>Audio resource"]
    Transcriptions["audio.transcriptions<br/>Transcriptions class"]
    Translations["audio.translations<br/>Translations class"]
    Speech["audio.speech<br/>Speech class"]
    
    Client -->|".audio"| AudioResource
    AudioResource -->|".transcriptions"| Transcriptions
    AudioResource -->|".translations"| Translations
    AudioResource -->|".speech"| Speech
    
    Transcriptions -->|"create()"| TranscriptionAPI["POST /audio/transcriptions<br/>returns TranscriptionCreateResponse"]
    Translations -->|"create()"| TranslationAPI["POST /audio/translations<br/>returns Translation"]
    Speech -->|"create()"| SpeechAPI["POST /audio/speech<br/>returns HttpxBinaryResponseContent"]
```

**Implementation:** [src/openai/resources/audio/transcriptions.py:45](), [src/openai/resources/audio/translations.py:30](), [src/openai/resources/audio/speech.py:28]()

### Audio Transcriptions

The transcriptions API converts audio files to text using Whisper or GPT-4o models. It supports multiple response formats and optional features like speaker diarization and word-level timestamps.

#### Basic Transcription

```mermaid
graph LR
    Input["Audio File<br/>(mp3, wav, etc.)"]
    Method["client.audio.transcriptions.create()"]
    Params["TranscriptionCreateParams<br/>- file: FileTypes<br/>- model: AudioModel<br/>- response_format: str"]
    Response["TranscriptionCreateResponse<br/>Union of:<br/>- Transcription<br/>- TranscriptionVerbose<br/>- TranscriptionDiarized"]
    
    Input --> Method
    Params --> Method
    Method --> Response
```

**Stream Event Types:**
The API supports streaming transcriptions via Server-Sent Events (SSE). [src/openai/resources/audio/transcriptions.py:129-136]()

| Event Type | Description |
|------------|-------------|
| `TranscriptionTextSegmentEvent` | Complete segment with timing |
| `TranscriptionTextDeltaEvent` | Incremental text updates |
| `TranscriptionTextDoneEvent` | Final completion event |

**Response Formats:**
The `response_format` parameter controls the returned structure:
- **`"json"`**: Returns `Transcription` with text. [src/openai/resources/audio/transcriptions.py:87]()
- **`"verbose_json"`**: Returns `TranscriptionVerbose` with segment timing. [src/openai/resources/audio/transcriptions.py:144]()
- **`"text"`, `"srt"`, `"vtt"`**: Returns raw strings. [src/openai/resources/audio/transcriptions.py:125]()

Sources: [src/openai/resources/audio/transcriptions.py:68-152](), [src/openai/types/audio/transcription_stream_event.py]()

### Audio Translations

The translations API converts audio in any supported language to English text. It uses the `whisper-1` model. [src/openai/resources/audio/translations.py:125]()

**Key Types:**
- `Translation`: Basic translated text. [src/openai/types/audio/translation.py]()
- `TranslationVerbose`: Detailed response with segment metadata. [src/openai/types/audio/translation_verbose.py]()

Sources: [src/openai/resources/audio/translations.py:103-165]()

### Audio Speech Synthesis (TTS)

The speech API converts text to spoken audio. It returns binary audio content.

**Key Parameters:**
- `model`: One of `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`. [src/openai/resources/audio/speech.py:77]()
- `voice`: Supported voices like `alloy`, `echo`, `nova`, `shimmer`. [src/openai/resources/audio/speech.py:79-81]()
- `response_format`: `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm`. [src/openai/resources/audio/speech.py:89]()

**Return Type:** Returns `_legacy_response.HttpxBinaryResponseContent`, providing raw bytes. [src/openai/resources/audio/speech.py:128]()

Sources: [src/openai/resources/audio/speech.py:50-129]()

---

## Images API

The `images` resource provides operations for image generation, editing, and variations.

### Images Resource Operations

```mermaid
graph TB
    ImagesResource["client.images<br/>Images resource class"]
    
    Generate["generate()<br/>POST /images/generations"]
    Edit["edit()<br/>POST /images/edits"]
    Variation["create_variation()<br/>POST /images/variations"]
    
    ImagesResource --> Generate
    ImagesResource --> Edit
    ImagesResource --> Variation
    
    Generate --> Response["ImagesResponse"]
    Edit --> Response
    Variation --> Response
```

**Implementation:** [src/openai/resources/images.py:28]()

### Image Generation and Streaming

The `generate()` method creates images from text prompts. It supports standard generation and streaming for GPT image models. [src/openai/resources/images.py:209]()

**Streaming Support:**
GPT image models (`gpt-image-1.5`, etc.) support streaming partial image data. [src/openai/types/image_generate_params.py:145]()

| Event Type | Contains |
|------------|----------|
| `ImageGenPartialImageEvent` | Incremental base64 image data |
| `ImageGenCompletedEvent` | Final image with metadata |

Sources: [src/openai/resources/images.py:209-260](), [src/openai/types/image_generate_params.py:13-160](), [src/openai/types/image_gen_stream_event.py]()

### Image Editing and Variations

- **`edit()`**: Modifies an image based on a prompt. Requires a square PNG for `dall-e-2` or up to 16 images for GPT models. [src/openai/types/image_edit_params.py:15-24]()
- **`create_variation()`**: Creates a variation of a given image. Only supports `dall-e-2`. [src/openai/resources/images.py:68]()

Sources: [src/openai/resources/images.py:50-126](), [src/openai/types/image_edit_params.py:11-160]()

---

## Video APIs

The `videos` resource manages video generation jobs, supporting creation, editing, and remixing using models like `sora-2`.

### Video Operations Lifecycle

```mermaid
sequenceDiagram
    participant App as "Application"
    participant Videos as "client.videos"
    participant API as "OpenAI Video API"
    
    App->>Videos: create(prompt, model="sora-2")
    Videos->>API: POST /videos
    API-->>Videos: Video object (status: pending)
    Videos-->>App: Video object
    
    App->>Videos: poll(video_id)
    loop until status is complete
        Videos->>API: GET /videos/{id}
        API-->>Videos: Video object
    end
    Videos-->>App: Final Video object
```

**Key Methods:**
- **`create()`**: Starts a generation job. [src/openai/resources/videos.py:69]()
- **`create_and_poll()`**: Convenience method to create and wait for completion. [src/openai/resources/videos.py:137]()
- **`edit()`**: Edits an existing video. [src/openai/resources/videos.py:237]()
- **`remix()`**: Creates a remix of a video. [src/openai/resources/videos.py:408]()
- **`extend()`**: Extends a video's duration. [src/openai/resources/videos.py:494]()

**Key Parameters:**
- `seconds`: Clip duration (4, 8, 12). [src/openai/resources/videos.py:95]()
- `size`: Resolution (e.g., `1280x720`, `1792x1024`). [src/openai/resources/videos.py:97]()

Sources: [src/openai/resources/videos.py:49-550](), [src/openai/types/video_create_params.py]()

---

## File Handling Patterns

Media APIs use `extract_files` and `deepcopy_with_paths` to handle binary uploads (multipart/form-data).

```mermaid
graph LR
    RawInput["FileTypes<br/>(bytes, Path, IO)"]
    DeepCopy["deepcopy_with_paths()<br/>src/openai/_files.py"]
    Extract["extract_files()<br/>src/openai/_utils.py"]
    Request["HTTP POST<br/>multipart/form-data"]
    
    RawInput --> DeepCopy
    DeepCopy --> Extract
    Extract --> Request
```

**Implementation Details:**
- **Multipart Headers**: The SDK explicitly sets `Content-Type: multipart/form-data` for file-bearing requests. [src/openai/resources/files.py:139](), [src/openai/resources/videos.py:122]()
- **File Extraction**: The `extract_files` utility separates binary content from JSON metadata for the HTTP client. [src/openai/_utils.py:135]()

Sources: [src/openai/resources/files.py:127-143](), [src/openai/resources/videos.py:108-123](), [src/openai/_utils.py:16]()

---

## Tool Integration (Multi-Modal)

The SDK's type system allows media generation to be integrated as tools in conversational contexts via the `ToolParam` and `Tool` definitions.

| Tool Type | Code Entity | Purpose |
|-----------|-------------|---------|
| Image Generation | `ImageGeneration` | Allows models to generate images as a tool call. |
| Computer Use | `ComputerTool` | Visual interaction with computer interfaces. |

Sources: [src/openai/types/responses/tool_param.py:39](), [src/openai/types/responses/tool.py:10-40]()

---

## Error Handling and Validation

Media APIs validate inputs before transmission using `maybe_transform`.

- **Audio Validation**: Checks for supported formats (flac, mp3, etc.). [src/openai/resources/audio/transcriptions.py:96-97]()
- **Image Validation**: Checks size limits (4MB for `dall-e-2`) and PNG requirements. [src/openai/types/image_edit_params.py:23-25]()
- **Video Validation**: Validates `VideoSize` and `VideoSeconds` against allowed literal values. [src/openai/resources/videos.py:92-98]()

Sources: [src/openai/resources/audio/transcriptions.py:142](), [src/openai/types/image_edit_params.py:14-138](), [src/openai/resources/videos.py:124]()

---

# Page: Additional API Resources

# Additional API Resources

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/admin/organization/__init__.py](src/openai/resources/admin/organization/__init__.py)
- [src/openai/resources/admin/organization/invites.py](src/openai/resources/admin/organization/invites.py)
- [src/openai/resources/admin/organization/organization.py](src/openai/resources/admin/organization/organization.py)
- [src/openai/resources/admin/organization/projects/__init__.py](src/openai/resources/admin/organization/projects/__init__.py)
- [src/openai/resources/admin/organization/projects/projects.py](src/openai/resources/admin/organization/projects/projects.py)
- [src/openai/resources/admin/organization/projects/spend_alerts.py](src/openai/resources/admin/organization/projects/spend_alerts.py)
- [src/openai/resources/admin/organization/projects/spend_limit.py](src/openai/resources/admin/organization/projects/spend_limit.py)
- [src/openai/resources/admin/organization/spend_alerts.py](src/openai/resources/admin/organization/spend_alerts.py)
- [src/openai/resources/admin/organization/spend_limit.py](src/openai/resources/admin/organization/spend_limit.py)
- [src/openai/resources/batches.py](src/openai/resources/batches.py)
- [src/openai/resources/containers/containers.py](src/openai/resources/containers/containers.py)
- [src/openai/resources/containers/files/files.py](src/openai/resources/containers/files/files.py)
- [src/openai/resources/skills/skills.py](src/openai/resources/skills/skills.py)
- [src/openai/resources/skills/versions/versions.py](src/openai/resources/skills/versions/versions.py)
- [src/openai/resources/uploads/parts.py](src/openai/resources/uploads/parts.py)
- [src/openai/resources/videos.py](src/openai/resources/videos.py)
- [src/openai/types/admin/organization/__init__.py](src/openai/types/admin/organization/__init__.py)
- [src/openai/types/admin/organization/invite_create_params.py](src/openai/types/admin/organization/invite_create_params.py)
- [src/openai/types/admin/organization/organization_spend_limit.py](src/openai/types/admin/organization/organization_spend_limit.py)
- [src/openai/types/admin/organization/organization_spend_limit_deleted.py](src/openai/types/admin/organization/organization_spend_limit_deleted.py)
- [src/openai/types/admin/organization/projects/__init__.py](src/openai/types/admin/organization/projects/__init__.py)
- [src/openai/types/admin/organization/usage_audio_speeches_response.py](src/openai/types/admin/organization/usage_audio_speeches_response.py)
- [src/openai/types/admin/organization/usage_audio_transcriptions_response.py](src/openai/types/admin/organization/usage_audio_transcriptions_response.py)
- [src/openai/types/admin/organization/usage_code_interpreter_sessions_response.py](src/openai/types/admin/organization/usage_code_interpreter_sessions_response.py)
- [src/openai/types/admin/organization/usage_completions_response.py](src/openai/types/admin/organization/usage_completions_response.py)
- [src/openai/types/admin/organization/usage_costs_response.py](src/openai/types/admin/organization/usage_costs_response.py)
- [src/openai/types/admin/organization/usage_embeddings_response.py](src/openai/types/admin/organization/usage_embeddings_response.py)
- [src/openai/types/admin/organization/usage_images_response.py](src/openai/types/admin/organization/usage_images_response.py)
- [src/openai/types/admin/organization/usage_moderations_response.py](src/openai/types/admin/organization/usage_moderations_response.py)
- [src/openai/types/admin/organization/usage_vector_stores_response.py](src/openai/types/admin/organization/usage_vector_stores_response.py)
- [src/openai/types/batch.py](src/openai/types/batch.py)
- [src/openai/types/batch_create_params.py](src/openai/types/batch_create_params.py)
- [src/openai/types/batch_list_params.py](src/openai/types/batch_list_params.py)
- [src/openai/types/container_create_params.py](src/openai/types/container_create_params.py)
- [src/openai/types/container_create_response.py](src/openai/types/container_create_response.py)
- [src/openai/types/container_list_params.py](src/openai/types/container_list_params.py)
- [src/openai/types/container_list_response.py](src/openai/types/container_list_response.py)
- [src/openai/types/container_retrieve_response.py](src/openai/types/container_retrieve_response.py)
- [src/openai/types/eval_create_params.py](src/openai/types/eval_create_params.py)
- [src/openai/types/evals/create_eval_completions_run_data_source.py](src/openai/types/evals/create_eval_completions_run_data_source.py)
- [src/openai/types/evals/create_eval_completions_run_data_source_param.py](src/openai/types/evals/create_eval_completions_run_data_source_param.py)
- [src/openai/types/evals/run_cancel_response.py](src/openai/types/evals/run_cancel_response.py)
- [src/openai/types/evals/run_create_params.py](src/openai/types/evals/run_create_params.py)
- [src/openai/types/evals/run_create_response.py](src/openai/types/evals/run_create_response.py)
- [src/openai/types/evals/run_list_response.py](src/openai/types/evals/run_list_response.py)
- [src/openai/types/evals/run_retrieve_response.py](src/openai/types/evals/run_retrieve_response.py)
- [src/openai/types/graders/score_model_grader.py](src/openai/types/graders/score_model_grader.py)
- [src/openai/types/graders/score_model_grader_param.py](src/openai/types/graders/score_model_grader_param.py)
- [src/openai/types/moderation.py](src/openai/types/moderation.py)
- [src/openai/types/moderation_create_params.py](src/openai/types/moderation_create_params.py)
- [src/openai/types/moderation_image_url_input_param.py](src/openai/types/moderation_image_url_input_param.py)
- [src/openai/types/moderation_model.py](src/openai/types/moderation_model.py)
- [src/openai/types/moderation_multi_modal_input_param.py](src/openai/types/moderation_multi_modal_input_param.py)
- [src/openai/types/moderation_text_input_param.py](src/openai/types/moderation_text_input_param.py)
- [src/openai/types/responses/response_function_shell_tool_call_output.py](src/openai/types/responses/response_function_shell_tool_call_output.py)
- [src/openai/types/video_create_params.py](src/openai/types/video_create_params.py)
- [tests/api_resources/admin/organization/projects/test_spend_alerts.py](tests/api_resources/admin/organization/projects/test_spend_alerts.py)
- [tests/api_resources/admin/organization/test_spend_alerts.py](tests/api_resources/admin/organization/test_spend_alerts.py)
- [tests/api_resources/test_batches.py](tests/api_resources/test_batches.py)
- [tests/api_resources/test_containers.py](tests/api_resources/test_containers.py)
- [tests/api_resources/test_videos.py](tests/api_resources/test_videos.py)

</details>



This page documents API resources that provide supporting functionality for the OpenAI SDK. These include model introspection, content moderation, batch processing, video generation, evaluation tools, skills management, and administrative organization management.

For conversational AI, see [Chat Completions API](#4.1) and [Responses API](#4.2). For specialized features, see [Assistants API (Beta)](#4.3), [Fine-Tuning API](#4.4), [Embeddings and Vector Stores](#4.5), [File Management and Uploads](#4.6), and [Audio, Images, and Video APIs](#4.7).

## Resource Overview

The SDK exposes these additional API resources through the main client:

| Resource | Purpose | Client Access |
|----------|---------|---------------|
| **Models** | Retrieve model metadata, list available models, delete fine-tuned models | `client.models` |
| **Moderations** | Classify text and images for policy violations | `client.moderations` |
| **Batches** | Process large volumes of requests asynchronously | `client.batches` |
| **Videos** | Create and manage high-fidelity video generation jobs | `client.videos` |
| **Evals** | Create and run evaluations to benchmark model performance | `client.beta.evals` |
| **Skills** | Manage reusable model capabilities and tool definitions | `client.beta.skills` |
| **Containers** | Manage containerized environments and associated files | `client.beta.containers` |
| **Admin** | Manage organization-level usage, costs, and project resources | `client.admin` |

**Sources:** [src/openai/resources/batches.py:25-26](), [src/openai/resources/videos.py:49-50](), [src/openai/resources/skills/skills.py:1-15](), [src/openai/resources/containers/containers.py:1-15]()

## Models API

The Models API provides introspection capabilities for available models and management of fine-tuned models.

### Resource Structure

```mermaid
graph TB
    ["OpenAI Client"] -- "client.models" --> ModelsResource["Models (src/openai/resources/models.py)"]
    ModelsResource -- "retrieve(model)" --> Model["Model (src/openai/types/model.py)"]
    ModelsResource -- "list()" --> Model
    ModelsResource -- "delete(model)" --> ModelDeleted["ModelDeleted (src/openai/types/model_deleted.py)"]
    
    Model --> ID["id: str"]
    Model --> Created["created: int"]
    Model --> OwnedBy["owned_by: str"]
    
    ModelDeleted --> DeletedID["id: str"]
    ModelDeleted --> Deleted["deleted: bool"]
```

**Sources:** [src/openai/resources/models.py:49-110](), [src/openai/types/model.py:7-15]()

### Methods
- **Retrieve Model Information**: Retrieves metadata for a specific model using `client.models.retrieve(model_id)`. [src/openai/resources/models.py:84-100]()
- **List Available Models**: Retrieves all models available to the API key. Returns a `SyncPage[Model]` with standard pagination support. [src/openai/resources/models.py:102-110]()
- **Delete Fine-Tuned Models**: Deletes a fine-tuned model owned by your organization using `client.models.delete(model_id)`. [src/openai/resources/models.py:61-82]()

---

## Moderations API

The Moderations API classifies content for policy violations across multiple categories. It supports text, image, and multi-modal inputs. [src/openai/types/moderation.py:1-181]()

### Content Categories
The API evaluates content across categories such as `harassment`, `hate`, `self-harm`, `sexual`, and `violence`. Scores and flagged statuses are provided per category. [src/openai/types/moderation.py:13-91]()

### Request and Response
The `Moderations.create()` method accepts `input` which can be a string or a list of multi-modal objects. [src/openai/types/moderation_create_params.py:13-30]()

The response `Moderation` object contains:
- `flagged`: Boolean indicating if content violates policies. [src/openai/types/moderation.py:193-193]()
- `categories`: `Categories` model mapping category names to booleans. [src/openai/types/moderation.py:182-183]()
- `category_scores`: `CategoryScores` model mapping category names to confidence scores. [src/openai/types/moderation.py:190-191]()
- `category_applied_input_types`: Specifies if the score applies to `text` or `image`. [src/openai/types/moderation.py:185-188]()

**Sources:** [src/openai/types/moderation.py:13-193](), [src/openai/types/moderation_create_params.py:13-30]()

---

## Batches API

The Batches API processes large volumes of requests asynchronously. This is cost-effective for non-time-sensitive workloads (24-hour turnaround). [src/openai/resources/batches.py:25-26]()

### Batch Data Flow

```mermaid
graph LR
    InputFile["JSONL File (purpose='batch')"] -- "input_file_id" --> Create["Batches.create()"]
    Create -- "POST /batches" --> BatchObj["Batch (src/openai/types/batch.py)"]
    BatchObj -- "Poll status" --> Retrieve["Batches.retrieve()"]
    Retrieve -- "If 'completed'" --> OutputFile["output_file_id (JSONL)"]
    
    subgraph "Batch States"
        S1["validating"] --> S2["in_progress"]
        S2 --> S3["completed"]
        S2 --> S4["failed"]
        S2 --> S5["cancelled"]
    end
```

**Sources:** [src/openai/types/batch.py:7-110](), [src/openai/resources/batches.py:47-133]()

### Usage
- **Create**: `client.batches.create()` requires `completion_window` (currently only `24h`), an `endpoint` (e.g., `/v1/chat/completions`), and an `input_file_id`. [src/openai/resources/batches.py:47-133]()
- **Supported Endpoints**: Includes `/v1/responses`, `/v1/chat/completions`, `/v1/embeddings`, `/v1/completions`, `/v1/moderations`, `/v1/images/generations`, `/v1/images/edits`, and `/v1/videos`. [src/openai/types/batch_create_params.py:20-31]()
- **Monitor**: `client.batches.retrieve(batch_id)` returns the current status and `request_counts`. [src/openai/resources/batches.py:135-170]()
- **Cancel**: `client.batches.cancel(batch_id)` stops an in-progress batch. [src/openai/resources/batches.py:204-226]()

---

## Videos API

The Videos API handles high-fidelity video generation jobs, supporting models like `sora-2` and `sora-2-pro`. [src/openai/resources/videos.py:49-50](), [src/openai/resources/videos.py:92-93]()

### Key Methods
- **`create()`**: Initiates a video generation job from a `prompt`. Supports optional `input_reference` for assets, `seconds` (4, 8, 12), and `size` (resolution). [src/openai/resources/videos.py:69-135]()
- **`create_and_poll()`**: Convenience method that initiates the job and blocks until completion. [src/openai/resources/videos.py:137-170]()
- **`poll()`**: Wait for a specific `video_id` to reach a terminal state, using `X-Stainless-Poll-Helper` headers. [src/openai/resources/videos.py:171-205]()

**Sources:** [src/openai/resources/videos.py:69-205](), [src/openai/types/video_create_params.py:13-30]()

---

## Evals API (Beta)

The Evals API facilitates benchmarking model performance by creating evaluation groups and running them against specific data sources. [src/openai/types/eval_create_params.py:38-43]()

### Evaluation Components
- **Data Source**: Configured via `DataSourceConfig`. Supports `custom` (JSON schema), `logs` (metadata filters), and `stored_completions`. [src/openai/types/eval_create_params.py:67-111]()
- **Testing Criteria**: A list of graders. Supported graders include `LabelModel`, `TextSimilarity`, `Python`, and `ScoreModel`. [src/openai/types/eval_create_params.py:45-51](), [src/openai/types/eval_create_params.py:189-203]()
- **Runs**: Execution of evaluations via `client.beta.evals.runs.create()`. Supports `ReasoningEffort` for `o-series` models. [src/openai/types/evals/run_create_params.py:42-59](), [src/openai/types/evals/run_create_params.py:118-127]()

**Sources:** [src/openai/types/eval_create_params.py:38-111](), [src/openai/types/evals/run_create_params.py:42-146]()

---

## Admin and Organization API

The Admin API provides organization-level management for auditing, usage tracking, and project resource constraints.

### Audit Logs
The `client.admin.organization.audit_logs.list()` method retrieves a history of actions performed within the organization. [src/openai/resources/admin/organization/audit_logs.py:1-20]()
- **Actors**: Tracks if an action was performed by a `session` (user) or an `api_key`. [src/openai/types/admin/organization/audit_log_list_response.py:147-158]()
- **Events**: Logs events like `api_key.created`, `project.updated`, `user.added`, and `invite.sent`. [src/openai/types/admin/organization/audit_log_list_response.py:18-90]()

### Usage and Costs
Detailed usage metrics and cost tracking are available via specialized response models:
- **Completions**: `UsageCompletionsResponse` [src/openai/types/admin/organization/usage_completions_response.py:1-10]()
- **Costs**: `UsageCostsResponse` [src/openai/types/admin/organization/usage_costs_response.py:1-10]()
- **Other Metrics**: Includes `embeddings`, `images`, `moderations`, `vector_stores`, and `audio` (speech/transcription). [src/openai/types/admin/organization/usage_embeddings_response.py:1-10](), [src/openai/types/admin/organization/usage_audio_transcriptions_response.py:1-10]()

### Organization Management
- **Projects**: Manage isolated environments within an organization via `client.admin.organization.projects`. [src/openai/resources/admin/organization/projects/projects.py:1-20]()
- **Invites**: Manage user invitations via `client.admin.organization.invites`. [src/openai/resources/admin/organization/invites.py:1-10]()
- **Spend Alerts/Limits**: Configure alerts and limits for budget management. [src/openai/resources/admin/organization/spend_alerts.py:1-10](), [src/openai/resources/admin/organization/spend_limit.py:1-10]()

**Sources:** [src/openai/resources/admin/organization/audit_logs.py:1-20](), [src/openai/types/admin/organization/__init__.py:1-82](), [src/openai/resources/admin/organization/projects/projects.py:1-20]()

---

# Page: Realtime API (Beta)

# Realtime API (Beta)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/lib/_realtime.py](src/openai/lib/_realtime.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/beta/realtime/sessions.py](src/openai/resources/beta/realtime/sessions.py)
- [src/openai/resources/realtime/__init__.py](src/openai/resources/realtime/__init__.py)
- [src/openai/resources/realtime/calls.py](src/openai/resources/realtime/calls.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [src/openai/types/beta/realtime/session.py](src/openai/types/beta/realtime/session.py)
- [src/openai/types/beta/realtime/session_create_params.py](src/openai/types/beta/realtime/session_create_params.py)
- [src/openai/types/beta/realtime/session_create_response.py](src/openai/types/beta/realtime/session_create_response.py)
- [src/openai/types/beta/realtime/session_update_event.py](src/openai/types/beta/realtime/session_update_event.py)
- [src/openai/types/beta/realtime/session_update_event_param.py](src/openai/types/beta/realtime/session_update_event_param.py)
- [src/openai/types/realtime/__init__.py](src/openai/types/realtime/__init__.py)
- [src/openai/types/realtime/call_accept_params.py](src/openai/types/realtime/call_accept_params.py)
- [src/openai/types/realtime/call_create_params.py](src/openai/types/realtime/call_create_params.py)
- [src/openai/types/realtime/call_refer_params.py](src/openai/types/realtime/call_refer_params.py)
- [src/openai/types/realtime/call_reject_params.py](src/openai/types/realtime/call_reject_params.py)
- [src/openai/types/realtime/realtime_response_create_mcp_tool.py](src/openai/types/realtime/realtime_response_create_mcp_tool.py)
- [src/openai/types/realtime/realtime_response_create_mcp_tool_param.py](src/openai/types/realtime/realtime_response_create_mcp_tool_param.py)
- [src/openai/types/realtime/realtime_session_create_request.py](src/openai/types/realtime/realtime_session_create_request.py)
- [src/openai/types/realtime/realtime_session_create_request_param.py](src/openai/types/realtime/realtime_session_create_request_param.py)
- [src/openai/types/realtime/realtime_session_create_response.py](src/openai/types/realtime/realtime_session_create_response.py)
- [src/openai/types/realtime/realtime_tools_config_param.py](src/openai/types/realtime/realtime_tools_config_param.py)
- [src/openai/types/realtime/realtime_tools_config_union.py](src/openai/types/realtime/realtime_tools_config_union.py)
- [src/openai/types/realtime/realtime_tools_config_union_param.py](src/openai/types/realtime/realtime_tools_config_union_param.py)
- [src/openai/types/responses/response_includable.py](src/openai/types/responses/response_includable.py)
- [src/openai/types/video_edit_params.py](src/openai/types/video_edit_params.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



The Realtime API enables low-latency, multi-modal conversational experiences through WebSocket and WebRTC connections. It supports text and audio as both input and output, as well as function calling. This page documents the WebSocket-based API implementation and the WebRTC (SDP) integration in the `openai-python` library.

For standard REST-based chat interactions, see [Chat Completions API](#4.1). For stateful assistant conversations using threads and runs, see [Assistants API (Beta)](#4.3).

## Connection Architecture

The Realtime API uses WebSocket connections managed through connection managers. The library provides both synchronous and asynchronous implementations with identical interfaces.

### Connection Lifecycle

```mermaid
graph TB
    Client["OpenAI / AsyncOpenAI Client"]
    RealtimeResource["Realtime Resource<br/>client.realtime"]
    ConnectMethod["connect() Method<br/>Returns ConnectionManager"]
    ContextManager["RealtimeConnectionManager /<br/>AsyncRealtimeConnectionManager"]
    WebsocketLib["websockets Library<br/>ClientConnection"]
    ConnObj["RealtimeConnection /<br/>AsyncRealtimeConnection"]
    Resources["Resource Interfaces:<br/>- session<br/>- response<br/>- input_audio_buffer<br/>- conversation<br/>- output_audio_buffer"]
    
    Client --> RealtimeResource
    RealtimeResource --> ConnectMethod
    ConnectMethod --> ContextManager
    ContextManager -->|"__enter__ / __aenter__"| WebsocketLib
    WebsocketLib --> ConnObj
    ConnObj --> Resources
    
    ContextManager -.->|"__exit__ / __aexit__<br/>Ensures close()"| WebsocketLib
```

**Sources:** [src/openai/resources/realtime/realtime.py:69-136](), [src/openai/resources/realtime/realtime.py:139-206](), [src/openai/resources/realtime/realtime.py:531-635](), [src/openai/resources/realtime/realtime.py:348-452]()

The connection flow follows this pattern:

1.  **Resource Access**: The client exposes `client.realtime` [src/openai/_client.py:83]().
2.  **Connection Initiation**: Call `connect(model="gpt-realtime")` to get a connection manager [src/openai/resources/realtime/realtime.py:99-136]().
3.  **Context Manager**: Use as a context manager to automatically handle connection lifecycle [src/openai/resources/realtime/realtime.py:348-353]().
4.  **Connection Object**: Inside the context, receive a `RealtimeConnection` or `AsyncRealtimeConnection`.
5.  **Resource Interfaces**: The connection object exposes typed resource interfaces for sending events.
6.  **Automatic Cleanup**: The context manager ensures the WebSocket is closed on exit.

### WebSocket URL Construction

The library constructs WebSocket URLs differently for standard OpenAI and Azure deployments. The `OpenAI` client uses `websocket_base_url` or defaults to the standard base URL with a scheme replacement.

| Client Type | URL Pattern | Query Parameters |
| :--- | :--- | :--- |
| `OpenAI` / `AsyncOpenAI` | `wss://{base_url}/v1/realtime` | `model={model}` |
| `AzureOpenAI` / `AsyncAzureOpenAI` | `wss://{azure_endpoint}/openai/realtime` | `api-version={version}`, `deployment={deployment}` |

**Sources:** [src/openai/_client.py:118-124](), [src/openai/resources/realtime/realtime.py:438-445](), [src/openai/resources/realtime/realtime.py:621-628]()

## Event-Based Communication Model

The Realtime API uses bidirectional event streaming. Client events are sent to the server, and server events are received and parsed.

### Event Types and Flow

```mermaid
sequenceDiagram
    participant App as "Application"
    participant Conn as "RealtimeConnection"
    participant WS as "WebSocket"
    participant API as "OpenAI API"
    
    App->>Conn: connect(model="gpt-realtime")
    Conn->>WS: Open WebSocket
    WS->>API: WSS Connection
    API-->>WS: session.created event
    WS-->>Conn: recv()
    Conn-->>App: RealtimeServerEvent
    
    App->>Conn: session.update(...)
    Conn->>WS: send(JSON)
    WS->>API: Client Event (session.update)
    API-->>WS: session.updated event
    
    App->>Conn: input_audio_buffer.append(audio)
    Conn->>WS: send(JSON)
    Note over API: VAD Detection
    API-->>WS: input_audio_buffer.speech_started
    
    App->>Conn: response.create()
    Conn->>WS: send(JSON)
    API-->>WS: response.created
    API-->>WS: response.output_audio.delta
    API-->>WS: response.done
```

**Sources:** [src/openai/resources/realtime/realtime.py:306-345](), [src/openai/resources/realtime/realtime.py:489-528]()

### Client Events

Client events are sent through typed resource interfaces on the connection object. The library provides methods that construct properly formatted event dictionaries:

*   **Session Events**: `connection.session.update(session={...})` [src/openai/resources/realtime/realtime.py:642-662]()
*   **Response Events**: `connection.response.create()`, `connection.response.cancel()` [src/openai/resources/realtime/realtime.py:664-708]()
*   **Audio Buffer Events**: `connection.input_audio_buffer.append()`, `connection.input_audio_buffer.commit()`, `connection.input_audio_buffer.clear()` [src/openai/resources/realtime/realtime.py:710-758]()

### Server Events

Server events are received by iterating over the connection object. Events are automatically parsed into `RealtimeServerEvent` objects [src/openai/resources/realtime/realtime.py:293-304]().

```python
async for event in connection:
    if event.type == "response.output_audio.delta":
        process_audio(event.delta)
    elif event.type == "session.created":
        print(f"Session ID: {event.session.id}")
```

**Sources:** [src/openai/resources/realtime/realtime.py:476-487]()

## Session Configuration

Sessions are configured using `session.update()`. This defines the model behavior, modalities, and audio processing parameters.

### Session Parameters

Key configuration options in `RealtimeSessionCreateResponse`:

*   **`model`**: The Realtime model to use (e.g., `gpt-4o-realtime-preview`) [src/openai/types/realtime/realtime_session_create_request.py:57-82]().
*   **`output_modalities`**: Set of modalities (`text`, `audio`) the model can respond with [src/openai/types/realtime/realtime_session_create_request.py:84-90]().
*   **`turn_detection`**: Controls Voice Activity Detection (VAD).
    *   `server_vad`: Server detects speech start/end automatically [src/openai/types/realtime/realtime_session_create_response.py:58-64]().
    *   `semantic_vad`: Advanced turn detection using a model to estimate turn completion [src/openai/types/realtime/realtime_session_create_response.py:128-134]().
*   **`instructions`**: System instructions prepended to model calls [src/openai/types/realtime/realtime_session_create_request.py:34-48]().

**Sources:** [src/openai/types/realtime/realtime_session_create_response.py:165-250](), [src/openai/types/realtime/realtime_session_create_request.py:18-147]()

## WebRTC and Phone Integration (Calls)

The `calls` resource provides methods for integrating with WebRTC and SIP/phone systems.

### WebRTC SDP Handshake

To establish a peer-to-peer audio connection, the client sends an SDP offer and receives an SDP answer from the API via `client.realtime.calls.create`.

```python
# Create a WebRTC call
answer_sdp = client.realtime.calls.create(
    sdp=offer_sdp,
    session={"model": "gpt-4o-realtime-preview"}
)
```

**Sources:** [src/openai/resources/realtime/realtime.py:75-78](), [src/openai/resources/realtime/calls.py:61-108]()

### Call Management Methods

| Method | Purpose | Key Parameters |
| :--- | :--- | :--- |
| `create` | Create WebRTC call via SDP offer | `sdp`, `session` |
| `accept` | Accept an incoming SIP call | `call_id`, `model`, `instructions` |
| `reject` | Reject an incoming call | `call_id` |
| `refer` | Transfer a call to another destination | `call_id`, `to` |

**Sources:** [src/openai/resources/realtime/calls.py:41-248]()

## Audio Streaming Details

Audio data is handled as base64-encoded strings of raw PCM bytes.

### Audio Formats

The API supports several audio formats for input and output:
*   **PCM16**: 16-bit PCM at 24kHz, mono, little-endian.
*   **G.711 u-law**: Standard telephony format.
*   **G.711 a-law**: Standard telephony format.

**Sources:** [src/openai/types/realtime/realtime_audio_formats.py:1-15]() (implied by type), [src/openai/types/realtime/realtime_session_create_response.py:166-167]()

### Audio Buffer Management

```mermaid
graph LR
    App["Application"]
    Buffer["input_audio_buffer"]
    API["Realtime API"]
    
    App -->|append| Buffer
    Buffer -->|commit| API
    Buffer -->|clear| API
    
    API -.->|speech_started| App
    API -.->|committed| App
```

**Sources:** [src/openai/resources/realtime/realtime.py:710-758]()

## Reconnection and State Management

The SDK handles WebSocket reconnection logic through the `RealtimeConnectionManager`.

### Reconnection Logic

*   **Recoverable Closes**: The client attempts to reconnect if the closure is deemed recoverable [src/openai/types/websocket_reconnection.py:49]().
*   **Backoff**: Uses exponential backoff with `initial_delay`, `max_delay`, and `max_retries` [src/openai/resources/realtime/realtime.py:108-110]().
*   **Queueing**: A `SendQueue` manages messages that need to be sent once the connection is re-established [src/openai/resources/realtime/realtime.py:37]().

**Sources:** [src/openai/resources/realtime/realtime.py:406-432](), [src/openai/resources/realtime/realtime.py:589-615]()

### Error Handling

Errors are returned as `RealtimeErrorEvent` server events rather than raising Python exceptions during the stream.

```python
if event.type == "error":
    print(f"Error {event.error.code}: {event.error.message}")
```

**Sources:** [src/openai/types/realtime/realtime_error_event.py:1-20]()

## Implementation Mapping

```mermaid
classDiagram
    class Realtime {
        +connect() RealtimeConnectionManager
        +calls Calls
        +client_secrets ClientSecrets
    }
    class RealtimeConnection {
        +session RealtimeSessionResource
        +response RealtimeResponseResource
        +input_audio_buffer RealtimeInputAudioBufferResource
        +send(event)
    }
    class Calls {
        +create(sdp, session)
        +accept(call_id, ...)
    }
    class RealtimeServerEvent {
        +type string
        +session Session
        +delta string
    }
    
    Realtime --> RealtimeConnection : creates via manager
    Realtime --> Calls : exposes
    RealtimeConnection --> RealtimeServerEvent : yields in iteration
```

**Sources:** [src/openai/resources/realtime/realtime.py:69-78](), [src/openai/resources/realtime/realtime.py:214-250](), [src/openai/resources/realtime/calls.py:41-60]()

---

# Page: Data Types and Type System

# Data Types and Type System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.stats.yml](.stats.yml)
- [api.md](api.md)
- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



This document provides an overview of the OpenAI Python SDK's comprehensive type system. Types are automatically generated from the OpenAPI specification (referenced in [.stats.yml:2]()) and built on Pydantic with compatibility layers supporting both Pydantic v1 and v2. The type system encompasses request parameter types, response models, type coercion mechanisms, and special sentinel values.

For details on data transformation and validation processes that operate on these types, see [Data Transformation and Validation](#6). For information about how types are used in specific API resources, see [API Resources and Endpoints](#4).

## Overview

The SDK's type system is **generated from an OpenAPI specification** (278 configured endpoints as of [.stats.yml:1]()) and provides compile-time type safety through static type checkers like `mypy` and `pyright`. The library implements a dual type system that distinguishes between input parameters and output responses:

- **Type Generation**: Types are automatically generated from the OpenAPI spec stored at the URL in [.stats.yml:2]().
- **Request Parameters**: Defined using `TypedDict` with `total=False`, allowing flexible optional parameters [src/openai/_utils/_transform.py:99-105]().
- **Response Models**: Defined using custom Pydantic `BaseModel` subclasses with additional methods and compatibility shims [src/openai/_models.py:101-119]().
- **Compatibility Layer**: Abstracts differences between Pydantic v1 and v2 APIs through the `PYDANTIC_V1` flag [src/openai/_utils/__init__.py:36-42]().
- **Type Transformation**: The `transform` function handles mapping Python-style keys to API-style aliases (e.g., `foo_bar` to `fooBar`) using `PropertyInfo` metadata [src/openai/_utils/_transform.py:44-76]().
- **Special Sentinels**: `NotGiven` and `Omit` distinguish between absent parameters, explicit nulls, and values to remove [src/openai/_types.py:133-188]().

**Type System Architecture**

```mermaid
graph TB
    subgraph "Type Generation"
        OpenAPISpec["OpenAPI Specification<br/>.stats.yml references<br/>278 endpoints"]
        StainlessGen["Stainless Code Generator<br/>(external tool)"]
        OpenAPISpec --> StainlessGen
    end
    
    subgraph "Generated Types"
        TypesModule["src/openai/types/<br/>Generated from OpenAPI"]
        SharedTypes["src/openai/types/shared.py<br/>Metadata, ChatModel,<br/>FunctionDefinition"]
        ChatTypes["src/openai/types/chat/<br/>ChatCompletion,<br/>CompletionCreateParams"]
        
        StainlessGen --> TypesModule
        TypesModule --> SharedTypes
        TypesModule --> ChatTypes
    end
    
    subgraph "Type System Foundation"
        PydanticBase["pydantic.BaseModel<br/>(external dependency)"]
        
        BaseModel["src/openai/_models.py<br/>BaseModel class<br/>to_dict(), to_json()"]
        
        CompatLayer["src/openai/_compat.py<br/>PYDANTIC_V1 flag<br/>model_dump(), get_origin()"]
        
        TransformLogic["src/openai/_utils/_transform.py<br/>transform(), PropertyInfo"]
        
        Sentinels["src/openai/_types.py<br/>NotGiven, Omit"]
    end
    
    PydanticBase --> BaseModel
    CompatLayer -.provides.-> BaseModel
    
    ChatTypes --> BaseModel
    
    PropertyInfo -.used by.-> TransformLogic
    TransformLogic -.processes.-> ChatTypes
    Sentinels -.handled by.-> TransformLogic
    
    User["User Code"] --> ChatTypes
```

Sources: [.stats.yml:1-4](), [src/openai/_models.py:101-210](), [src/openai/_types.py:133-188](), [src/openai/_utils/_transform.py:44-76](), [src/openai/types/__init__.py:1-121]()

## Type System Components

### Core Type Definitions

The type system is organized across several modules:

| Module | Purpose | Example Types |
|--------|---------|---------------|
| `src/openai/_models.py` | Base model classes and construction logic | `BaseModel`, `GenericModel` |
| `src/openai/_compat.py` | Pydantic v1/v2 compatibility layer | `PYDANTIC_V1`, `model_dump` |
| `src/openai/types/shared/` | Shared types across multiple resources | `ErrorObject`, `FunctionDefinition` |
| `src/openai/types/__init__.py` | Exported types for end-users | `ChatModel`, `FileObject`, `Completion` |
| `src/openai/_types.py` | Internal utility types and sentinels | `NotGiven`, `Omit`, `FileTypes` |

The `BaseModel` class at [src/openai/_models.py:101-210]() extends `pydantic.BaseModel` with:

- **Enhanced serialization**: `to_dict()` and `to_json()` methods with `use_api_names` parameter to control key casing [src/openai/_models.py:139-210]().
- **Request ID tracking**: `_request_id` property for debugging (top-level responses only) [src/openai/_models.py:123-137]().

Sources: [src/openai/_models.py:101-210](), [src/openai/types/__init__.py:10-29](), [src/openai/_types.py:1-250]()

### Request vs Response Type Pattern

```mermaid
graph LR
    subgraph "Request Flow (Code Entity Space)"
        UserParams["User provides<br/>dict or kwargs"]
        ParamType["TypedDict<br/>(e.g. CompletionCreateParams)"]
        Transform["_transform_recursive()<br/>Apply PropertyInfo aliases"]
        JSONBody["API Request Body<br/>(camelCase keys)"]
    end
    
    subgraph "Response Flow (Code Entity Space)"
        JSONResp["API Response Body<br/>(JSON)"]
        ParseResp["construct_type()<br/>Coerce to Pydantic"]
        ResponseModel["BaseModel<br/>(e.g. ChatCompletion)"]
        UserAccess["User accesses<br/>snake_case attributes"]
    end
    
    UserParams --> ParamType
    ParamType --> Transform
    Transform --> JSONBody
    
    JSONResp --> ParseResp
    ParseResp --> ResponseModel
    ResponseModel --> UserAccess
```

**Request Parameters** use `TypedDict` to provide type hints while allowing standard Python dictionaries. The `transform` utility at [src/openai/_utils/_transform.py:92-113]() maps snake_case keys to API-required aliases defined in `PropertyInfo` [src/openai/_utils/_transform.py:44-76]().

**Response Types** use Pydantic models that inherit from `BaseModel`. These models ensure that data returned from the API is validated and provides attribute-style access (e.g., `completion.choices[0].message`) [api.md:36, 94]().

Sources: [src/openai/_utils/_transform.py:44-113](), [src/openai/_models.py:101-137](), [api.md:36, 94]()

### Type Transformation and Metadata

The SDK uses `Annotated` types combined with `PropertyInfo` to manage how data is converted for the API.

- **PropertyInfo**: Metadata class storing `alias` (e.g., `fooBar`), `format` (e.g., `iso8601`), and `discriminator` [src/openai/_utils/_transform.py:44-76]().
- **_transform_recursive**: The engine that walks through nested dictionaries, lists, and unions to apply these transformations [src/openai/_utils/_transform.py:154-209]().

Sources: [src/openai/_utils/_transform.py:44-209](), [tests/test_transform.py:40-61]()

### Special Types and Sentinels

The library uses sentinel types to handle the ambiguity between "null" and "undefined" in API requests [src/openai/_types.py:133-188]().

- `NotGiven`: Used for parameters where the user didn't provide a value. This allows the SDK to omit the key from the JSON request instead of sending `null` [src/openai/_types.py:133-164]().
- `Omit`: Used to explicitly remove a key that might otherwise be included by default (e.g., headers) [src/openai/_types.py:166-188]().
- `FileTypes`: A complex union type for file uploads, supporting `bytes`, `pathlib.Path`, and tuples containing filenames and MIME types [src/openai/_types.py:72-81]().

Sources: [src/openai/_types.py:72-188](), [src/openai/_utils/_utils.py:160-161]()

## Child Pages

For more technical detail on specific components of the type system, see the following pages:

- [Type System Overview](#5.1) — Architecture and code generation from OpenAPI.
- [Request Parameter Types](#5.2) — Documentation on `TypedDict` parameters and key transformation.
- [Response Types and Models](#5.3) — Details on Pydantic response structures and validation.
- [Pydantic Models and BaseModel](#5.4) — Custom features of the `BaseModel` class and v1/v2 compatibility.
- [Special Types and Sentinels](#5.5) — Usage of `NotGiven`, `Omit`, and `FileTypes` for binary data.

Sources: [src/openai/_models.py:101-210](), [src/openai/types/__init__.py:1-121](), [src/openai/_types.py:1-250]()

---

# Page: Type System Overview

# Type System Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.stats.yml](.stats.yml)
- [api.md](api.md)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared/all_models.py](src/openai/types/shared/all_models.py)
- [src/openai/types/shared/responses_model.py](src/openai/types/shared/responses_model.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [src/openai/types/shared_params/responses_model.py](src/openai/types/shared_params/responses_model.py)

</details>



## Purpose and Scope

This document explains the architecture of the OpenAI Python SDK's type system, including how types are generated from OpenAPI specifications, how they are organized into categories, and how they provide compile-time and runtime type safety. For details on specific type categories, see [Request Parameter Types](#5.2), [Response Types and Models](#5.3), and [Pydantic Models and BaseModel](#5.4). For sentinel values and special types, see [Special Types and Sentinels](#5.5).

The type system serves three primary goals:
1. **Compile-time type safety** via `mypy` and `pyright` type checkers.
2. **Runtime validation** via Pydantic models for API responses.
3. **Developer experience** through accurate IDE autocomplete and inline documentation.

## Type Generation Architecture

The SDK's types are automatically generated from OpenAI's OpenAPI specification using Stainless's code generation tooling. This ensures types stay synchronized with the API as it evolves.

Title: Type Generation Data Flow
```mermaid
graph TB
    OPENAPI["OpenAPI Specification<br/>(openapi_spec_url in .stats.yml)"]
    STAINLESS["Stainless Code Generator"]
    
    GENERATED["Generated Type Files<br/>src/openai/types/"]
    
    SHARED["Shared Types<br/>src/openai/types/shared/"]
    PARAMS["Parameter Types<br/>*_params.py files"]
    RESPONSES["Response Models<br/>*.py files"]
    
    EXPORTS["Type Exports<br/>src/openai/types/__init__.py"]
    
    CLIENT["Client Code<br/>References types"]
    
    OPENAPI --> STAINLESS
    STAINLESS --> GENERATED
    
    GENERATED --> SHARED
    GENERATED --> PARAMS
    GENERATED --> RESPONSES
    
    SHARED --> EXPORTS
    PARAMS --> EXPORTS
    RESPONSES --> EXPORTS
    
    EXPORTS --> CLIENT
```

**Sources:** [.stats.yml:1-5](), [src/openai/types/__init__.py:1-125]()

### OpenAPI Specification Source

The type system is generated from a specific OpenAPI specification version, tracked in the codebase:

| Configuration Key | Purpose | Value |
|-------------------|---------|-------|
| `openapi_spec_url` | Points to Stainless storage with versioned OpenAPI YAML | `https://storage.googleapis.com/stainless-sdk-openapi-specs/openai/openai-0650ebae454b4200491980d7663cb7ceabcff90dcb3ed9f67c3bca3e861a2bf6.yml` |
| `openapi_spec_hash` | MD5 hash ensuring spec integrity | `e9576bced964246b7e685a5ad30afffa` |
| `configured_endpoints` | Count of API endpoints | `278` |

The specification hash ensures reproducible builds and allows detecting when the API shape changes.

**Sources:** [.stats.yml:1-5]()

## Type Organization Structure

Types are organized into a hierarchical directory structure that mirrors the API's resource organization.

Title: Directory and Entity Mapping
```mermaid
graph TB
    ROOT["src/openai/types/"]
    
    SHARED["shared/<br/>Cross-API types"]
    SHARED_PARAMS["shared_params/<br/>Cross-API parameter types"]
    
    CHAT["chat/<br/>Chat API types"]
    AUDIO["audio/<br/>Audio API types"]
    
    ROOT --> SHARED
    ROOT --> SHARED_PARAMS
    ROOT --> CHAT
    ROOT --> AUDIO
    
    SHARED -.exports.-> METADATA["Metadata"]
    SHARED -.exports.-> REASONING["Reasoning"]
    SHARED -.exports.-> CHATMODEL["ChatModel"]
    
    SHARED_PARAMS -.exports.-> METADATAPARAM["Metadata param"]
    SHARED_PARAMS -.exports.-> REASONINGPARAM["Reasoning param"]
    
    CHAT -.exports.-> CHATCOMP["ChatCompletion"]
    CHAT -.exports.-> CHATCOMPPARAM["completion_create_params.py"]
```

**Sources:** [src/openai/types/__init__.py:1-125](), [src/openai/types/shared/__init__.py:1-21](), [src/openai/types/shared_params/__init__.py:1-17]()

### Directory Structure

| Directory | Purpose | Example Types |
|-----------|---------|---------------|
| `types/` | Root-level types and top-level resource types | `FileObject`, `Model`, `Completion`, `Batch` |
| `types/shared/` | Types shared across multiple API response contexts | `Metadata`, `ChatModel`, `Reasoning`, `ErrorObject` |
| `types/shared_params/` | Parameter types shared across multiple request contexts | `Metadata`, `ComparisonFilter`, `FunctionDefinition` |
| `types/chat/` | Chat Completions API types | `ChatCompletion`, `ChatCompletionMessage` |
| `types/audio/` | Audio API types | `AudioModel`, `AudioResponseFormat` |

**Sources:** [src/openai/types/__init__.py:1-125](), [api.md:1-167]()

## Type Categories

The type system divides types into three primary categories, each serving a distinct role in the request/response lifecycle.

Title: Request/Response Type Lifecycle
```mermaid
graph LR
    subgraph "Request Flow (TypedDict)"
        USER["User Code"]
        PARAMS["completion_create_params.py"]
        TRANSFORM["Data Transformation"]
        REQUEST["HTTP Request"]
    end
    
    subgraph "Response Flow (Pydantic)"
        RESPONSE["HTTP Response"]
        PARSE["Response Parsing"]
        MODELS["chat_completion.py"]
        USERDATA["User Code"]
    end
    
    subgraph "Shared Space"
        SHARED["shared/chat_model.py"]
    end
    
    USER --> PARAMS
    PARAMS --> TRANSFORM
    TRANSFORM --> REQUEST
    
    RESPONSE --> PARSE
    PARSE --> MODELS
    MODELS --> USERDATA
    
    SHARED -.used by.-> PARAMS
    SHARED -.used by.-> MODELS
```

**Sources:** [src/openai/types/__init__.py:1-125](), [src/openai/types/shared/__init__.py:1-21]()

### 1. Shared Types

Shared types represent data structures used across multiple API endpoints. They are often defined twice: once in `types/shared/` for responses (Pydantic-compatible) and once in `types/shared_params/` for requests (TypedDict-compatible).

| Type Name | Purpose | Implementation File |
|-----------|---------|---------|
| `ChatModel` | Union of valid chat model identifiers | `src/openai/types/shared/chat_model.py` |
| `Metadata` | Optional metadata key-value pairs | `src/openai/types/shared/metadata.py` |
| `ReasoningEffort` | Configuration for model reasoning depth | `src/openai/types/shared/reasoning_effort.py` |
| `FunctionDefinition` | Tool function definition schema | `src/openai/types/shared/function_definition.py` |
| `AllModels` | Broad union of all supported model strings | `src/openai/types/shared/all_models.py` |
| `ResponsesModel` | Models specifically for the Responses API | `src/openai/types/shared/responses_model.py` |

**Sources:** [src/openai/types/shared/chat_model.py:1-91](), [src/openai/types/shared/all_models.py:1-30](), [src/openai/types/shared/responses_model.py:1-30](), [src/openai/types/shared_params/responses_model.py:1-32]()

### 2. Parameter Types (Request)

Parameter types define the shape of data sent to the API. They are implemented as `TypedDict` classes to allow users to pass plain Python dictionaries while maintaining type safety.

| Parameter Type | Endpoint | Source File |
|----------------|----------|------|
| `CompletionCreateParams` | `POST /chat/completions` | `src/openai/types/chat/completion_create_params.py` |
| `FileCreateParams` | `POST /files` | `src/openai/types/file_create_params.py` |
| `EmbeddingCreateParams` | `POST /embeddings` | `src/openai/types/embedding_create_params.py` |
| `ImageGenerateParams` | `POST /images/generations` | `src/openai/types/image_generate_params.py` |

**Sources:** [src/openai/types/__init__.py:66-125](), [api.md:94-116]()

### 3. Response Models (Pydantic)

Response models define the shape of data returned from the API. These are implemented as Pydantic models, providing runtime validation and easy attribute access.

| Response Model | Returned By | Source File |
|----------------|-------------|----------|
| `ChatCompletion` | `client.chat.completions.create` | `src/openai/types/chat/chat_completion.py` |
| `FileObject` | `client.files.create` | `src/openai/types/file_object.py` |
| `CreateEmbeddingResponse` | `client.embeddings.create` | `src/openai/types/create_embedding_response.py` |
| `ImagesResponse` | `client.images.generate` | `src/openai/types/images_response.py` |
| `Batch` | `client.batches.create` | `src/openai/types/batch.py` |

**Sources:** [src/openai/types/__init__.py:5-51](), [api.md:94-158]()

## Type Safety Guarantees

The SDK provides both compile-time and runtime type safety through multiple layers:

1.  **Compile-Time**: `AllModels` and `ResponsesModel` use `Literal` and `Union` types to restrict valid string inputs for model names at development time, including recent models like `o3-pro` and `o3-deep-research` [src/openai/types/shared/all_models.py:10-29]().
2.  **Runtime Validation**: API responses are parsed into Pydantic models, ensuring the data matches the expected schema [src/openai/types/__init__.py:1-125]().
3.  **Strict Typing**: The SDK uses `TypeAlias` and `from __future__ import annotations` to support modern Python typing features across supported versions [src/openai/types/shared/all_models.py:3-5]().

**Sources:** [src/openai/types/shared/all_models.py:1-30](), [src/openai/types/shared/responses_model.py:1-30](), [src/openai/types/__init__.py:1-125]()

---

# Page: Request Parameter Types

# Request Parameter Types

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [src/openai/types/beta/assistant_response_format_option.py](src/openai/types/beta/assistant_response_format_option.py)
- [src/openai/types/beta/assistant_response_format_option_param.py](src/openai/types/beta/assistant_response_format_option_param.py)
- [src/openai/types/beta/function_tool_param.py](src/openai/types/beta/function_tool_param.py)
- [src/openai/types/shared/function_definition.py](src/openai/types/shared/function_definition.py)
- [src/openai/types/shared_params/function_definition.py](src/openai/types/shared_params/function_definition.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



This document describes the `TypedDict`-based parameter type system used throughout the `openai-python` library. It covers how API method parameters are defined, validated, and transformed into HTTP requests.

For information about response types returned by the API, see [Response Types and Models (5.3)](). For details on sentinel values used in parameters, see [Special Types and Sentinels (5.5)](). For the broader type system architecture, see [Type System Overview (5.1)]().

## Purpose and Scope

Request parameter types in this library are defined as `TypedDict` classes that specify the structure and types of arguments passed to API methods. These types are generated from the OpenAPI specification and provide:

- **Type safety**: Static type checkers can validate parameter structures.
- **Documentation**: Field docstrings describe parameter purposes and constraints.
- **Runtime flexibility**: `TypedDict` allows both required and optional fields.
- **Validation separation**: Type checking occurs at development time; runtime transformation processes the data for the wire.

All parameter types are located in `src/openai/types/` and follow a consistent pattern across all API resources.

**Sources**: [src/openai/types/shared_params/function_definition.py:1-46](), [src/openai/_utils/_transform.py:92-112]()

## TypedDict Parameter Pattern

### Base Parameter Structure

All API method parameters are defined as `TypedDict` classes with `total=False`, meaning all fields are optional by default unless explicitly marked with `Required[]`.

```mermaid
graph TB
    subgraph "Code Entity Space: typing_extensions"
        TypedDict["TypedDict(total=False)"]
        Required["Required[T]"]
    end

    subgraph "Natural Language Space: Parameter Definition"
        Mandatory["Mandatory Field"]
        Optional["Optional Field"]
    end

    TypedDict --> Mandatory
    TypedDict --> Optional
    Mandatory --- Required

    subgraph "Example Entity: FunctionDefinition (shared_params)"
        FD["FunctionDefinition<br/>function_definition.py:13"]
        name["name: Required[str]<br/>Line 14"]
        desc["description: str<br/>Line 21"]
        strict["strict: Optional[bool]<br/>Line 38"]
    end

    FD --> name
    FD --> desc
    FD --> strict
```

**Diagram: TypedDict Parameter Structure and Code Mapping**

The `total=False` setting combined with `Required[]` provides precise control over which fields must be provided:

| Field Declaration | User Must Provide | Can Be None | Can Be Omitted |
|------------------|------------------|-------------|----------------|
| `Required[T]` | Yes | No | No |
| `Optional[T]` | No | Yes | Yes |
| `T` (no wrapper) | No | No | Yes |

**Sources**: [src/openai/types/shared_params/function_definition.py:13-46](), [src/openai/_utils/_typing.py:44-46]()

## Required and Optional Fields

### Required Field Annotation

Fields marked with `Required[]` must be provided by the caller. The type system enforces this at development time. The utility function `is_required_type` is used internally to detect these markers.

```python
class FunctionDefinition(TypedDict, total=False):
    name: Required[str]
    """The name of the function to be called."""
```

**Sources**: [src/openai/types/shared_params/function_definition.py:14-15](), [src/openai/_utils/_typing.py:44-46]()

### Optional Field Patterns

Optional fields can be declared in several ways. The SDK distinguishes between an explicit `None` and a field being "not given" using the `NotGiven` sentinel.

| Field Name | Type | Meaning |
|-----------|------|---------|
| `description` | `str` | Can provide string or omit entirely |
| `strict` | `Optional[bool]` | Can provide bool, None, or omit |
| `parameters` | `FunctionParameters` | Can provide dict or omit |

**Sources**: [src/openai/types/shared_params/function_definition.py:21-46](), [src/openai/_types.py:133-161]()

## Transformation Logic

The SDK uses a recursive transformation pipeline to prepare `TypedDict` data for the API. This process handles aliases, formatting (like ISO8601 for dates), and recursive processing of nested dictionaries.

### PropertyInfo and Aliasing

The `PropertyInfo` class provides metadata for field transformation, such as mapping a Pythonic field name to an API-expected alias.

```python
class MyParams(TypedDict):
    account_holder_name: Annotated[str, PropertyInfo(alias='accountHolderName')]
```

When `transform` is called, it inspects these annotations to rename keys before the request is sent to the HTTP client.

**Sources**: [src/openai/_utils/_transform.py:44-75](), [src/openai/_utils/_transform.py:131-148]()

### File Extraction

For multipart requests, the SDK recursively extracts file content from parameter dictionaries using `extract_files`. This utility mutates the dictionary by removing file fields and returning them as a separate list.

```mermaid
graph TD
    subgraph "Code Entity Space: _utils.py"
        EF["extract_files()<br/>Line 41"]
        EI["_extract_items()<br/>Line 79"]
        AS["_array_suffix()<br/>Line 65"]
    end

    subgraph "Natural Language Space: File Processing"
        Scanner["Recursive Path Scanner"]
        Formatter["Array Key Formatter"]
        Mover["Body-to-Multipart Mover"]
    end

    EF --> Scanner
    Scanner --- EI
    Formatter --- AS
    Scanner --> Formatter
    EI --> Mover
```

**Diagram: File Extraction Logic Mapping**

The extraction logic searches for `FileTypes` (which can be `bytes`, `PathLike`, or `IO[bytes]`) along specified paths.

**Sources**: [src/openai/_utils/_utils.py:41-62](), [src/openai/_utils/_utils.py:79-111](), [src/openai/_types.py:72-81]()

## Recursive Transformation Process

The `transform` function in `src/openai/_utils/_transform.py` performs the following operations:

1.  **Key Mapping**: Converts Python snake_case keys to API aliases using `PropertyInfo`.
2.  **Date Formatting**: Converts `date` and `datetime` objects to ISO8601 strings if `PropertyInfo(format="iso8601")` is present.
3.  **Nested Processing**: Recursively applies transformations to `list`, `dict`, and nested `TypedDict` objects.
4.  **Union Handling**: Attempts to transform data against all subtypes in a `Union`.

```python
def transform(data: _T, expected_type: object) -> _T:
    # Recursively processes dictionaries based on TypedDict annotations
    transformed = _transform_recursive(data, annotation=cast(type, expected_type))
    return cast(_T, transformed)
```

**Sources**: [src/openai/_utils/_transform.py:92-112](), [src/openai/_utils/_transform.py:154-209](), [tests/test_transform.py:50-83]()

## Summary of Parameter Types

| Type Category | Implementation | Usage |
|---------------|----------------|-------|
| **Request Parameters** | `TypedDict` | Passed as arguments to `.create()`, `.list()`, etc. |
| **Metadata** | `PropertyInfo` | Annotated on `TypedDict` fields for aliases/formats. |
| **Sentinels** | `NotGiven` / `Omit` | Used to distinguish between `None` and omitted fields. |
| **Files** | `FileTypes` | Union of types accepted for file uploads. |

**Sources**: [src/openai/_utils/_transform.py:44-60](), [src/openai/_types.py:133-189](), [src/openai/_utils/_utils.py:160-161]()

---

# Page: Response Types and Models

# Response Types and Models

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [src/openai/lib/_parsing/_responses.py](src/openai/lib/_parsing/_responses.py)
- [src/openai/types/conversations/conversation_item.py](src/openai/types/conversations/conversation_item.py)
- [src/openai/types/responses/__init__.py](src/openai/types/responses/__init__.py)
- [src/openai/types/responses/parsed_response.py](src/openai/types/responses/parsed_response.py)
- [src/openai/types/responses/response_item.py](src/openai/types/responses/response_item.py)
- [src/openai/types/responses/response_output_item.py](src/openai/types/responses/response_output_item.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)

</details>



This page documents the Pydantic-based response models returned by API method calls in the OpenAI Python SDK. These models provide type-safe, validated data structures for API responses across all endpoints.

For information about request parameter types (which use `TypedDict`), see **5.2 Request Parameter Types**. For details about the `BaseModel` foundation and its SDK-specific methods, see **5.4 Pydantic Models and BaseModel**.

## Overview

Response models in the SDK are Pydantic classes that represent structured data returned from OpenAI API endpoints. They differ from request parameter types in key ways:

| Aspect | Response Models | Request Parameter Types |
|--------|----------------|------------------------|
| **Base Class** | `BaseModel` (Pydantic extension) | `TypedDict` |
| **Purpose** | Parse and validate API responses | Type-hint request parameters |
| **Runtime Validation** | Yes, automatic | No (type hints only) |
| **Methods Available** | `.to_dict()`, `.to_json()`, `.model_copy()` | None (plain dictionaries) |
| **Location** | `src/openai/types/` | `src/openai/types/*/params.py` |

Response models are generated from the OpenAPI specification and provide strongly-typed access to API response data with automatic validation and parsing.

**Sources:** [src/openai/_models.py:111-210](), [src/openai/_compat.py:188-201](), [src/openai/types/responses/response.py:1-321]()

## Response Model Architecture

The SDK response models form a hierarchy rooted in a custom `BaseModel` that abstracts Pydantic version differences.

### Class Hierarchy Diagram
```mermaid
graph TB
    subgraph "Response Model Hierarchy"
        BaseModel["BaseModel<br/>(src/openai/_models.py)"]
        GenericModel["GenericModel<br/>(src/openai/_models.py)"]
        
        subgraph "Responses API Models"
            Response["Response<br/>(src/openai/types/responses/response.py)"]
            ParsedResponse["ParsedResponse[T]<br/>(src/openai/types/responses/parsed_response.py)"]
            CompactedResponse["CompactedResponse<br/>(src/openai/types/responses/compacted_response.py)"]
        end
        
        subgraph "Output Content Models"
            ResponseOutputMessage["ResponseOutputMessage<br/>(src/openai/types/responses/response_output_message.py)"]
            ResponseOutputText["ResponseOutputText<br/>(src/openai/types/responses/response_output_text.py)"]
        end
    end
    
    BaseModel --> Response
    BaseModel --> CompactedResponse
    BaseModel --> ResponseOutputMessage
    BaseModel --> ResponseOutputText
    BaseModel --> GenericModel
    GenericModel --> ParsedResponse
```

**Sources:** [src/openai/_models.py:111-111](), [src/openai/_models.py:140-140](), [src/openai/types/responses/response.py:59-59](), [src/openai/types/responses/parsed_response.py:112-112](), [src/openai/types/responses/response_output_message.py:1-20](), [src/openai/types/responses/response_output_text.py:1-20]()

### Natural Language to Code Entity Mapping
This diagram bridges API concepts to specific implementation classes in the codebase.

```mermaid
graph LR
    subgraph "Natural Language Concepts"
        NL_Response["Standard API Response"]
        NL_Parsed["Structured/Parsed Output"]
        NL_ToolCall["Function/Tool Call"]
        NL_Program["Programmatic Tool Execution"]
    end

    subgraph "Code Entity Space"
        CE_Response["class Response<br/>(src/openai/types/responses/response.py)"]
        CE_Parsed["class ParsedResponse<br/>(src/openai/types/responses/parsed_response.py)"]
        CE_ToolCall["class ResponseFunctionToolCall<br/>(src/openai/types/responses/response_function_tool_call.py)"]
        CE_Program["class Program<br/>(src/openai/types/responses/response_output_item.py)"]
    end

    NL_Response -.-> CE_Response
    NL_Parsed -.-> CE_Parsed
    NL_ToolCall -.-> CE_ToolCall
    NL_Program -.-> CE_Program
```

**Sources:** [src/openai/types/responses/response.py:59-306](), [src/openai/types/responses/parsed_response.py:112-127](), [src/openai/types/responses/response_function_tool_call.py:1-30](), [src/openai/types/responses/response_output_item.py:45-60]()

## Major Response Types

### Responses API Models
The `Response` model is the primary type for the modern Responses API. It includes a unique `_request_id` property (exposed from `BaseModel`) for debugging.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier for the response [src/openai/types/responses/response.py:61-61]() |
| `output` | `List[ResponseOutputItem]` | Array of content items generated [src/openai/types/responses/response.py:277-277]() |
| `usage` | `Optional[ResponseUsage]` | Token usage details [src/openai/types/responses/response.py:303-303]() |
| `status` | `ResponseStatus` | Current state of the response [src/openai/types/responses/response.py:295-295]() |

**Sources:** [src/openai/types/responses/response.py:59-306](), [src/openai/_models.py:133-147]()

### Parsed and Structured Responses
The SDK provides specialized models for handling structured outputs where the API response is automatically deserialized into a user-defined Pydantic model.

#### `ParsedResponse[ContentType]`
This model extends the standard `Response` and adds a `parsed` field to specific output items. It includes a convenience property `output_parsed` that searches for the first valid parsed content.

```python
# src/openai/types/responses/parsed_response.py
class ParsedResponse(Response, GenericModel, Generic[ContentType]):
    if TYPE_CHECKING:
        output: List[ParsedResponseOutputItem[ContentType]]
    else:
        output: List[ParsedResponseOutputItem]

    @property
    def output_parsed(self) -> Optional[ContentType]:
        for output in self.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "output_text" and content.parsed:
                        return content.parsed
        return None
```

**Sources:** [src/openai/types/responses/parsed_response.py:112-127](), [src/openai/lib/_parsing/_responses.py:53-141]()

## Accessing Response Data

### Direct Field Access
Response models expose fields as attributes. The SDK's `BaseModel` ensures that even nested objects are correctly instantiated as Pydantic models during parsing via the `construct` method or standard initialization.

```python
# Example of accessing nested data
# response is an instance of src.openai.types.responses.Response
print(response.id) 

# Accessing nested output items
for item in response.output:
    if item.type == "message":
        print(item.content)

# Accessing the Request ID for debugging (top-level only)
print(response._request_id)
```

**Sources:** [src/openai/_models.py:133-147](), [src/openai/types/responses/response.py:59-306](), [tests/test_models.py:26-31]()

### Serialization Methods
Every response model provides methods to export data back to standard Python formats:

1.  **`to_dict()`**: Recursively generates a dictionary representation. By default, it uses API names (aliases) like `fooBar` instead of Python property names like `foo_bar`. [src/openai/_models.py:149-185]()
2.  **`to_json()`**: Generates a JSON string representing the model as it would be received from the API. [src/openai/_models.py:187-210]()

## Type Safety and Discriminated Unions

The SDK heavily utilizes Pydantic discriminated unions for fields that can return multiple types of objects, such as `ResponseOutputItem` and `ParsedResponseOutputItem`. These use the `PropertyInfo(discriminator="type")` annotation to guide parsing.

### Output Item Union Structure
```mermaid
graph TD
    subgraph "ParsedResponseOutputItem (Union)"
        Item["Union[...]"]
    end
    
    Item --> Message["ParsedResponseOutputMessage<br/>(type: 'message')"]
    Item --> ToolCall["ParsedResponseFunctionToolCall<br/>(type: 'function_call')"]
    Item --> Reasoning["ResponseReasoningItem<br/>(type: 'reasoning')"]
    Item --> ImageCall["ImageGenerationCall<br/>(type: 'image_generation_call')"]
    Item --> Program["Program<br/>(type: 'program')"]
    Item --> McpCall["McpCall<br/>(type: 'mcp_call')"]
```

**Sources:** [src/openai/types/responses/parsed_response.py:76-109](), [src/openai/types/responses/response_output_item.py:29-165](), [src/openai/_utils.py:55-55]()

## Data Transformation Pipeline

When a response is received, the SDK uses internal utilities to transform raw JSON into these structured models.

1.  **`model_parse_json`**: Entry point for converting a raw HTTP body into a model instance, supporting both Pydantic v1 and v2. [src/openai/_compat.py:175-178]()
2.  **`construct_type`**: A utility for type coercion, handling unions, and recursive construction of models from dictionaries. [src/openai/_models.py:13-13](), [tests/test_models.py:13-13]()
3.  **`parse_response`**: Specifically handles the logic for `ParsedResponse`, iterating through output items and applying the appropriate Pydantic parsing for structured text and tool arguments. [src/openai/lib/_parsing/_responses.py:53-141]()

**Sources:** [src/openai/_compat.py:175-178](), [src/openai/lib/_parsing/_responses.py:53-141](), [src/openai/_models.py:149-185](), [src/openai/_utils/_json.py:11-25]()

---

# Page: Pydantic Models and BaseModel

# Pydantic Models and BaseModel

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)

</details>



## Purpose and Scope

This page documents the custom `BaseModel` class that extends Pydantic's `BaseModel` with SDK-specific features. The OpenAI Python SDK defines its own `BaseModel` in [src/openai/_models.py]() to provide:

1.  **Validation-free construction** via the `construct()` method for efficient API response parsing.
2.  **Serialization helpers** (`to_dict()`, `to_json()`) with API-specific conventions.
3.  **Pydantic v1/v2 compatibility** to support both major Pydantic versions seamlessly.
4.  **Loose type coercion** through `construct_type()` for flexible data handling of API responses.

All API response models inherit from this custom `BaseModel`.

**Sources:** [src/openai/_models.py:1-111](), [src/openai/_compat.py:1-21]()

---

## BaseModel Class Hierarchy

The SDK's `BaseModel` extends `pydantic.BaseModel` and serves as the foundation for all response models. It handles the differences between Pydantic versions internally so that the rest of the SDK can use a unified interface.

### Architecture Diagram

```mermaid
graph TB
    subgraph "Pydantic Library Space"
        PydanticBase["pydantic.BaseModel"]
    end
    
    subgraph "SDK Code Entity Space - src/openai/_models.py"
        SDKBase["BaseModel<br/>[line 111]"]
        GenModel["GenericModel<br/>[line 96]"]
    end
    
    subgraph "SDK Data Flow"
        Construct["BaseModel.construct()<br/>[line 247]"]
        ConstructType["construct_type()<br/>[line 544]"]
        ToDict["to_dict()<br/>[line 149]"]
    end
    
    subgraph "Generated Response Models"
        ChatComp["ChatCompletion"]
        Message["Message"]
    end
    
    PydanticBase --> SDKBase
    SDKBase --> GenModel
    SDKBase --> ChatComp
    SDKBase --> Message
    
    SDKBase -. "implements" .-> Construct
    SDKBase -. "implements" .-> ToDict
    Construct -. "delegates to" .-> ConstructType
```

**Sources:** [src/openai/_models.py:96-111](), [src/openai/_models.py:247-294](), [src/openai/_models.py:544-661]()

---

## Configuration and Compatibility

The `BaseModel` uses a compatibility layer in [src/openai/_compat.py]() to handle differences between Pydantic v1 and v2.

### Extra Fields and Forward Compatibility
The models are configured with `extra="allow"` to ensure that if the OpenAI API adds new fields to a response, the SDK does not crash during parsing.

*   **Pydantic v1**: Uses a `Config` inner class with `extra: Any = pydantic.Extra.allow` [src/openai/_models.py:120-121]().
*   **Pydantic v2**: Uses `model_config` with `ConfigDict(extra="allow", ...)` [src/openai/_models.py:128-130]().

### Request ID Tracking
Top-level response objects contain a `_request_id` field [src/openai/_models.py:133](). This is populated from the `X-Request-ID` header returned by the API and is useful for debugging. It is only defined for the top-level response object [src/openai/_models.py:136-141]().

**Sources:** [src/openai/_models.py:112-147](), [src/openai/_compat.py:20-21]()

---

## Recursive Construction: construct()

The `construct()` method is the primary way the SDK instantiates models from API responses. Unlike Pydantic's standard validation, this method bypasses strict validation for performance and relies on `construct_type()` for recursive instantiation.

### Execution Logic

1.  **Field Mapping**: It iterates through `model_fields` using `get_model_fields(cls)` [src/openai/_models.py:256]().
2.  **Alias Handling**: It looks for keys in the input dictionary using the field's alias (the API name) first, then the Python property name [src/openai/_models.py:257-260]().
3.  **Recursion**: For each field, it calls `_construct_field()` [src/openai/_models.py:461-473](), which in turn calls `construct_type()` to handle nested models or lists.
4.  **Extra Fields**: Any keys in the input not defined in the model are preserved in the instance's extra storage (`__dict__`) [src/openai/_models.py:267-278]().

### construct_type() Logic Flow

```mermaid
graph TD
    Start["construct_type(value, type_)<br/>[_models.py:544]"] --> IsAnnotated{"Is Annotated?"}
    IsAnnotated -->|Yes| Strip["strip_annotated_type()"]
    IsAnnotated -->|No| CheckUnion{"Is Union?"}
    Strip --> CheckUnion
    
    CheckUnion -->|Yes| HandleUnion["Handle Union/Discriminator<br/>[lines 575-610]"]
    CheckUnion -->|No| CheckModel{"Is BaseModel?"}
    
    CheckModel -->|Yes| CallConstruct["type_.construct(**value)<br/>[line 631]"]
    CheckModel -->|No| CheckList{"Is List?"}
    
    CheckList -->|Yes| MapList["Recurse on items<br/>[line 638]"]
    CheckList -->|No| Default["Return value (raw)"]
```

**Sources:** [src/openai/_models.py:247-294](), [src/openai/_models.py:544-661](), [src/openai/_models.py:461-473]()

---

## Serialization: to_dict and to_json

The SDK provides `to_dict()` and `to_json()` as the preferred methods for serializing models, wrapping Pydantic's version-specific dump methods.

### to_dict()
[src/openai/_models.py:149-185]()
Converts the model to a Python dictionary.
*   **use_api_names**: If `True` (default), uses the API keys (e.g., `foo_bar` becomes `fooBar`) via `by_alias=use_api_names` [src/openai/_models.py:180]().
*   **mode**: Can be `python` (preserves objects like `datetime`) or `json` (converts to primitives) [src/openai/_models.py:179]().

### to_json()
[src/openai/_models.py:187-220]()
Returns a JSON string representation.
*   **indent**: Defaults to `2` for readability [src/openai/_models.py:190]().
*   **exclude_unset**: Defaults to `True` to match API response behavior where missing fields are omitted [src/openai/_models.py:192]().

### Custom Encoding for openapi_dumps
The SDK uses a `_CustomEncoder` in [src/openai/_utils/_json.py]() to handle `BaseModel` instances during general JSON serialization. It automatically calls `model_dump` with `exclude_unset=True` and `by_alias=True` to ensure consistency with API formats [src/openai/_utils/_json.py:33-34]().

**Sources:** [src/openai/_models.py:149-220](), [src/openai/_utils/_json.py:28-35]()

---

## Pydantic v1 vs v2 Compatibility Layer

The SDK maintains compatibility through shims in [src/openai/_compat.py](). This allows the codebase to support both `pydantic>=1.9.0` and `pydantic>=2.0.0`.

| Feature | SDK Shim Function | Implementation Detail |
| :--- | :--- | :--- |
| **Parsing** | `parse_obj()` [line 80] | Calls `model.parse_obj` (v1) or `model.model_validate` (v2) [lines 81-84]. |
| **Metadata** | `get_model_fields()` [line 116] | Accesses `__fields__` (v1) or `model_fields` (v2) [lines 117-119]. |
| **Serialization** | `model_dump()` [line 138] | Handles `mode`, `exclude_unset`, and `by_alias` consistently across versions [lines 148-166]. |
| **JSON Serialization** | `model_json()` [line 128] | Calls `model.json()` (v1) or `model.model_dump_json()` (v2) [lines 129-131]. |
| **Schema** | `model_json_schema()` [line 181] | Calls `model.schema()` (v1) or `model.model_json_schema()` (v2) [lines 182-184]. |

**Sources:** [src/openai/_compat.py:20-21](), [src/openai/_compat.py:80-184]()

---

# Page: Special Types and Sentinels

# Special Types and Sentinels

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_proxy.py](src/openai/_utils/_proxy.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [src/openai/lib/_old_api.py](src/openai/lib/_old_api.py)
- [tests/lib/test_old_api.py](tests/lib/test_old_api.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_proxy.py](tests/test_utils/test_proxy.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



This page documents the special types and sentinel values used throughout the SDK to handle optional parameters, file inputs, and type-safe checking. These constructs enable precise control over API request parameters and distinguish between semantically different states like "not provided", "explicitly None", and "explicitly omitted".

For information about the broader type system and generated types, see [Type System Overview](5.1). For information about request parameter types and response models, see [Request Parameter Types](5.2) and [Response Types and Models](5.3).

---

## Sentinel Values

### NotGiven Sentinel

The `NotGiven` sentinel class provides a way to distinguish between three distinct parameter states:

1.  **Parameter not provided** - `foo()` or `foo(bar=not_given)`
2.  **Parameter explicitly set to None** - `foo(bar=None)`
3.  **Parameter explicitly set to a value** - `foo(bar="value")`

This distinction is critical for APIs where `None` has semantic meaning different from "use the default behavior".

Title: Parameter State Resolution
```mermaid
graph TB
    subgraph "Parameter States"
        NOTPROVIDED["not_given<br/>(NotGiven instance)"]
        NONE["None<br/>(NoneType)"]
        VALUE["Actual Value<br/>(str, int, etc)"]
    end
    
    subgraph "API Behavior"
        DEFAULT["Use API default"]
        SETNULL["Send null in JSON"]
        SENDVALUE["Send value in JSON"]
    end
    
    NOTPROVIDED --> DEFAULT
    NONE --> SETNULL
    VALUE --> SENDVALUE
    
    subgraph "Code Entities"
        EX1["create(timeout=not_given)<br/>or create()"]
        EX2["create(timeout=None)"]
        EX3["create(timeout=60)"]
    end
    
    EX1 --> NOTPROVIDED
    EX2 --> NONE
    EX3 --> VALUE
```

**Sources:** [src/openai/_types.py:133-164]()

#### Implementation

The `NotGiven` class is defined as a singleton with special behavior:

[src/openai/_types.py:133-164]()
```python
class NotGiven:
    """
    For parameters with a meaningful None value, we need to distinguish between
    the user explicitly passing None, and the user not passing the parameter at
    all.
    """
    def __bool__(self) -> Literal[False]:
        return False

    @override
    def __repr__(self) -> str:
        return "NOT_GIVEN"

not_given = NotGiven()
NOT_GIVEN = NotGiven()  # backwards compatibility
```

The class evaluates to `False` in boolean contexts and has a distinct representation for debugging.

**Sources:** [src/openai/_types.py:133-164]()

#### Usage in Type Signatures

Parameters that may be omitted use `NotGiven` in union types:

Title: Type Interpretation Flow
```mermaid
graph LR
    subgraph "Type Signature Pattern"
        PARAM["param: T | None | NotGiven"]
    end
    
    subgraph "Interpretation"
        T["T = Use this value"]
        N["None = Explicitly null"]
        NG["NotGiven = Don't send"]
    end
    
    PARAM --> T
    PARAM --> N
    PARAM --> NG
```

**Sources:** [src/openai/_types.py:133-151]()

---

### Omit Sentinel

The `Omit` sentinel explicitly removes values that would otherwise be included by default, particularly useful for header management:

[src/openai/_types.py:166-188]()
```python
class Omit:
    """
    To explicitly omit something from being sent in a request, use `omit`.
    
    # as the default `Content-Type` header is `application/json` that will be sent
    client.post("/upload/files", files={"file": b"my raw file content"})
    
    # instead you can remove the default `application/json` header by passing omit
    client.post(..., headers={"Content-Type": omit})
    """
    def __bool__(self) -> Literal[False]:
        return False

omit = Omit()
```

**Use Case: Removing Default Headers**

Title: Header Omission Logic
```mermaid
graph TD
    subgraph "Without Omit"
        REQ1["client.post(files=...)"]
        DEFAULT1["Default Content-Type:<br/>application/json"]
        CONFLICT1["Conflict with multipart<br/>form-data boundary"]
    end
    
    subgraph "With Omit"
        REQ2["client.post(..., headers={'Content-Type': omit})"]
        NODEFAULT["Content-Type header<br/>not sent"]
        CORRECT["Correct multipart<br/>boundary generated"]
    end
    
    REQ1 --> DEFAULT1 --> CONFLICT1
    REQ2 --> NODEFAULT --> CORRECT
```

**Sources:** [src/openai/_types.py:166-188]()

---

### is_given() TypeGuard

The `is_given()` function provides type-safe checking of sentinel values:

[src/openai/_utils/_utils.py:160-161]()
```python
def is_given(obj: _T | NotGiven | Omit) -> TypeGuard[_T]:
    return not isinstance(obj, NotGiven) and not isinstance(obj, Omit)
```

This function narrows the type to `_T`, excluding both `NotGiven` and `Omit`, enabling type checkers to understand that the value is safe to use.

Title: Type Narrowing with is_given
```mermaid
graph LR
    subgraph "Input Type"
        INPUT["value: T | NotGiven | Omit"]
    end
    
    subgraph "is_given() Check"
        CHECK["if is_given(value):"]
    end
    
    subgraph "Narrowed Type"
        OUTPUT["value: T<br/>(NotGiven and Omit excluded)"]
    end
    
    INPUT --> CHECK --> OUTPUT
```

**Usage in Data Transformation**

The transformation logic uses `is_given` to decide whether to process a field:

[src/openai/_utils/_transform.py:15-15](), [src/openai/_utils/_utils.py:160-161]()

**Sources:** [src/openai/_utils/_utils.py:160-161](), [src/openai/_utils/_transform.py:13-15]()

---

## File Type Specifications

### FileTypes

The `FileTypes` type union represents all supported ways to pass file content to the API:

[src/openai/_types.py:72-81]()
```python
FileTypes = Union[
    # file (or bytes)
    FileContent,
    # (filename, file (or bytes))
    Tuple[Optional[str], FileContent],
    # (filename, file (or bytes), content_type)
    Tuple[Optional[str], FileContent, Optional[str]],
    # (filename, file (or bytes), content_type, headers)
    Tuple[Optional[str], FileContent, Optional[str], Mapping[str, str]],
]
```

Title: FileTypes Mapping to Code Entities
```mermaid
graph TD
    FileTypes["FileTypes Union"]
    
    FileTypes --> SIMPLE["FileContent<br/>(IO[bytes] | bytes | PathLike)"]
    FileTypes --> NAMED["(filename, FileContent)"]
    FileTypes --> TYPED["(filename, FileContent, content_type)"]
    FileTypes --> FULL["(filename, FileContent, content_type, headers)"]
    
    SIMPLE --> USE1["file = open('data.pdf', 'rb')"]
    SIMPLE --> USE2["file = b'raw bytes'"]
    SIMPLE --> USE3["file = Path('data.pdf')"]
    
    NAMED --> USE4["file = ('report.pdf', content)"]
    TYPED --> USE5["file = ('report.pdf', content, 'application/pdf')"]
    FULL --> USE6["file = ('report.pdf', content, 'application/pdf', {'X-Custom': 'value'})"]
```

**Sources:** [src/openai/_types.py:59-81]()

### Base64FileInput

For APIs that require Base64-encoded file data in JSON payloads:

[src/openai/_types.py:59-64]()
```python
if TYPE_CHECKING:
    Base64FileInput = Union[IO[bytes], PathLike[str]]
else:
    Base64FileInput = Union[IO[bytes], PathLike]
```

Files are automatically encoded during transformation when `PropertyInfo(format="base64")` is specified.

**Sources:** [src/openai/_types.py:59-64](), [src/openai/_utils/_transform.py:41-58]()

---

## Other Special Types

### NoneType

A workaround to support `None` as a valid response type without requiring extensive overloads:

[src/openai/_types.py:114-117]()
```python
if TYPE_CHECKING:
    NoneType: Type[None]
else:
    NoneType = type(None)
```

**Sources:** [src/openai/_types.py:98-117]()

### Omittable

A type alias combining a type with the `Omit` sentinel:

[src/openai/_types.py:189-189]()
```python
Omittable = Union[_T, Omit]
```

**Sources:** [src/openai/_types.py:189-189]()

### PropertyInfo

Metadata used in `Annotated` types to provide transformation information like aliases or formats.

[src/openai/_utils/_transform.py:44-75]()
```python
class PropertyInfo:
    alias: str | None
    format: PropertyFormat | None
    format_template: str | None
    discriminator: str | None
```

**Sources:** [src/openai/_utils/_transform.py:44-75]()

---

## Integration with Request Processing

### Sentinel Value Flow

Title: Data Transformation Pipeline for Sentinels
```mermaid
graph TB
    subgraph "User Code"
        CALL["client.chat.completions.create(<br/>temperature=not_given,<br/>max_tokens=100,<br/>headers={'X-Custom': omit})"]
    end
    
    subgraph "strip_not_given()"
        STRIP["Remove NotGiven values<br/>from dictionary"]
    end
    
    subgraph "is_given() Checks"
        CHECK["Filter in transform pipeline<br/>(_transform_recursive)"]
    end
    
    subgraph "Final Request"
        RESULT["JSON: {max_tokens: 100}<br/>Headers: (X-Custom removed)"]
    end
    
    CALL --> STRIP
    STRIP --> CHECK
    CHECK --> RESULT
```

**Sources:** [src/openai/_utils/_utils.py:160-161](), [src/openai/_utils/__init__.py:28-28]()

### Recursive File Extraction

The `extract_files` utility recursively traverses data structures to find `FileTypes` instances based on a set of paths. It mutates the input dictionary by popping keys that correspond to file locations to prepare them for multipart encoding.

[src/openai/_utils/_utils.py:41-62]()
```python
def extract_files(
    query: Mapping[str, object],
    *,
    paths: Sequence[Sequence[str]],
    array_format: ArrayFormat = "brackets",
) -> list[tuple[str, FileTypes]]:
    # ...
```

**Sources:** [src/openai/_utils/_utils.py:41-157]()

---

## Summary Table

| Type/Sentinel | Purpose | Key Characteristics |
|--------------|---------|-------------------|
| `NotGiven` | Distinguish "not provided" from `None` | Evaluates to `False`, singleton instance `not_given` |
| `Omit` | Explicitly remove default values | Evaluates to `False`, singleton instance `omit` |
| `is_given()` | Type-safe sentinel checking | Returns `TypeGuard[_T]` for type narrowing |
| `FileTypes` | Multiple file input formats | Union of 4 tuple formats plus raw content |
| `Base64FileInput` | Files for JSON embedding | PathLike or IO[bytes] |
| `NoneType` | Typing workaround for `None` | Enables `cast_to=NoneType` without overloads |
| `Omittable[T]` | Optional omission | `Union[T, Omit]` |
| `PropertyInfo` | Field metadata | Used for aliases and formatting |

**Sources:** [src/openai/_types.py:72-189](), [src/openai/_utils/_utils.py:160-161](), [src/openai/_utils/_transform.py:44-75]()

---

# Page: Data Transformation and Validation

# Data Transformation and Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



## Purpose and Scope

This page documents the transformation pipeline in `src/openai/_utils/_transform.py` that converts Python objects and dictionaries into API-compatible JSON before requests are dispatched. The system is responsible for preparing data structures according to the expectations of the OpenAI API.

- **Field aliasing**: Mapping internal `snake_case` keys to API `camelCase` via `PropertyInfo.alias`.
- **Format conversion**: Converting complex types like `datetime` to ISO 8601 strings or local files to base64.
- **Type coercion**: Converting Pydantic models to JSON-serializable dictionaries.
- **Sentinel handling**: Stripping `NotGiven` and `Omit` values to differentiate between default behavior and explicit nulls.

The transformation occurs at request time. For the reverse process of parsing API responses into Python objects, see [Type Coercion and Construction](#6.3).

**Sources:** [src/openai/_utils/_transform.py:1-458]()

---

## PropertyInfo and Field Metadata

### PropertyInfo Class

The `PropertyInfo` class serves as a metadata container used within `Annotated` types to define how a specific field should be treated during the transformation process.

```python
class PropertyInfo:
    alias: str | None           # The key name used in the API request payload
    format: PropertyFormat | None  # Specification for data conversion (iso8601, base64, custom)
    format_template: str | None    # Template string for custom date formatting
    discriminator: str | None      # Field used to identify variants in discriminated unions
```

**Sources:** [src/openai/_utils/_transform.py:44-76]()

### Field Transformation Metadata

| Metadata Field | Purpose | Example |
|---|---|---|
| `alias` | Renames keys during transformation | `PropertyInfo(alias="modelId")` maps `model_id` → `modelId` |
| `format="iso8601"` | Converts date objects to strings | `datetime(2024, 1, 1)` → `"2024-01-01T00:00:00"` |
| `format="base64"` | Encodes file-like objects to base64 | `pathlib.Path("img.png")` → Base64 string |
| `format="custom"` | Applies custom date templates | Uses `format_template` for non-standard formats |
| `discriminator` | Resolves union types | Identifies which class to instantiate in a Union |

**Sources:** [src/openai/_utils/_transform.py:60-71](), [tests/test_transform.py:40-48](), [tests/test_transform.py:164-175]()

### Usage Pattern

`PropertyInfo` is typically embedded in `TypedDict` definitions for request parameters [src/openai/_utils/_transform.py:49-53]().

```python
class ChatParams(TypedDict):
    max_tokens: Annotated[int, PropertyInfo(alias='max_tokens')]
    stop_sequences: Annotated[List[str], PropertyInfo(alias='stop')]
```

**Sources:** [src/openai/_utils/_transform.py:45-53](), [tests/test_transform.py:40-48]()

---

## Transformation Pipeline

### Transformation Pipeline Architecture

**Diagram: Data Transformation Flow**

```mermaid
graph TB
    subgraph "Public API [_transform.py]"
        transform["transform(data, expected_type)<br/>[line 92]"]
        async_transform["async_transform(data, expected_type)<br/>[line 297]"]
        maybe_transform["maybe_transform(data, expected_type)<br/>[line 78]"]
    end
    
    subgraph "Internal Recursion [_transform.py]"
        _transform_recursive["_transform_recursive()<br/>[line 154]"]
        _async_transform_recursive["_async_transform_recursive()<br/>[line 320]"]
    end
    
    subgraph "Specific Handlers [_transform.py]"
        _transform_typeddict["_transform_typeddict()<br/>[line 263]"]
        dict_proc["Dictionary Processing<br/>[line 182]"]
        list_proc["List/Sequence Processing<br/>[line 186]"]
        _format_data["_format_data()<br/>[line 236]"]
    end
    
    maybe_transform --> transform
    transform --> _transform_recursive
    async_transform --> _async_transform_recursive
    
    _transform_recursive --> _transform_typeddict
    _transform_recursive --> dict_proc
    _transform_recursive --> list_proc
    _transform_recursive --> _format_data
    
    _transform_typeddict --> _maybe_transform_key["_maybe_transform_key()<br/>[line 131]"]
    _maybe_transform_key --> _get_annotated_type["_get_annotated_type()<br/>[line 116]"]
```

**Sources:** [src/openai/_utils/_transform.py:78-458](), [src/openai/_utils/_typing.py:76-80]()

### Transform Entry Points

The SDK provides synchronous and asynchronous variants of the transformation logic [src/openai/_utils/_transform.py:78-318]().

| Function | Signature | Purpose |
|---|---|---|
| `transform` | `(data: _T, expected_type: object) -> _T` | Standard synchronous transformation |
| `async_transform` | `async (data: _T, expected_type: object) -> _T` | Asynchronous version supporting `anyio` file reads |
| `maybe_transform` | `(data: object, expected_type: object) -> Any \| None` | Null-safe wrapper for `transform` |

**Sources:** [src/openai/_utils/_transform.py:78-113](), [src/openai/_utils/_transform.py:284-318]()

---

## Format Conversion

### Date and Datetime Formatting

The pipeline handles the conversion of Python `date` and `datetime` objects into API-compliant strings [src/openai/_utils/_transform.py:236-243]().

- **ISO 8601**: Standard format for most timestamp fields [src/openai/_utils/_transform.py:237]().
- **Custom Templates**: Uses `format_template` if the API requires a specific non-ISO string [src/openai/_utils/_transform.py:240]().

**Sources:** [src/openai/_utils/_transform.py:236-243](), [tests/test_transform.py:164-268]()

### Base64 File Encoding

For endpoints that accept files embedded in JSON (rather than multipart), the system encodes content to Base64 [src/openai/_utils/_transform.py:244-260]().

- **Synchronous**: Reads from `io.IOBase` or bytes [src/openai/_utils/_transform.py:251]().
- **Asynchronous**: Uses `anyio` to perform non-blocking reads of `pathlib.Path` objects [src/openai/_utils/_transform.py:412-416]().

**Sources:** [src/openai/_utils/_transform.py:244-260](), [src/openai/_utils/_transform.py:410-426]()

---

## Special Values and Sentinels

### NotGiven vs None vs Omit

The SDK uses sentinel classes in `src/openai/_types.py` to distinguish between three distinct states of a parameter [src/openai/_types.py:133-187]().

| Sentinel | Code Entity | Transformation Behavior |
|---|---|---|
| `NotGiven` | `not_given` | Field is omitted from the JSON payload entirely [src/openai/_utils/_transform.py:270](). |
| `None` | `None` | Field is sent as a JSON `null` [src/openai/_utils/_transform.py:86](). |
| `Omit` | `omit` | Explicitly removes a key from a dictionary (e.g., headers) [src/openai/_utils/_transform.py:270](). |

**Sources:** [src/openai/_types.py:133-187](), [src/openai/_utils/_utils.py:160-161](), [src/openai/_utils/_transform.py:269-273]()

---

## Type System Integration

### Type Inspection and Utility Functions

The transformation logic relies on runtime type inspection to navigate complex nested structures [src/openai/_utils/_typing.py:1-89]().

- `strip_annotated_type`: Unwraps `Annotated[T, ...]` or `Required[T]` to find the base type `T` [src/openai/_utils/_typing.py:76-80]().
- `extract_type_arg`: Extracts generic arguments from types like `List[T]` or `Dict[K, V]` [src/openai/_utils/_typing.py:83-88]().
- `is_typeddict`: Determines if a type is a `TypedDict`, triggering key-alias transformation [src/openai/_compat.py:42]().

**Sources:** [src/openai/_utils/_typing.py:21-88](), [src/openai/_compat.py:30-64]()

---

## Type Coercion and Construction

### Incoming Data Validation

While `transform` handles outgoing data, `construct_type` in `src/openai/_models.py` manages the instantiation of response models from API JSON [src/openai/_models.py:494-611]().

**Diagram: Response Construction Logic**

```mermaid
graph TD
    Data["API Response JSON"] --> Construct["construct_type(type_, data)<br/>[_models.py:494]"]
    Construct --> IsModel{"Is BaseModel?"}
    IsModel -->|"Yes"| Model["Model.construct(**data)<br/>[_models.py:111]"]
    IsModel -->|"No"| IsUnion{"Is Union?"}
    IsUnion -->|"Yes"| Union["Iterate variants & validate<br/>[_models.py:535]"]
    IsUnion -->|"No"| Coerce["Apply loose coercion<br/>(e.g., int -> float)<br/>[_models.py:590]"]
```

**Sources:** [src/openai/_models.py:494-611](), [src/openai/_models.py:590-595](), [src/openai/_models.py:111]()

### Discriminated Union Construction

The construction logic uses the `discriminator` field defined in `PropertyInfo` to efficiently route data to the correct class variant within a `Union` [src/openai/_models.py:545-551]().

**Sources:** [src/openai/_models.py:663-721](), [tests/test_models.py:657-834]()

---

# Page: Data Transformation Pipeline

# Data Transformation Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



## Purpose and Scope

The Data Transformation Pipeline prepares Python-native data structures for transmission to the OpenAI API. It converts user-friendly Python idioms (snake_case keys, `datetime` objects, `pathlib.Path` instances) into API-compatible formats (camelCase keys, ISO 8601 strings, base64-encoded content). This transformation is metadata-driven, using type annotations to declaratively specify conversion rules.

This document covers the `transform()` and `async_transform()` functions and their supporting infrastructure. For details about the `PropertyInfo` metadata class that drives transformations, see [PropertyInfo and Field Metadata](#6.2). For information about sentinel values used during transformation, see [Special Types and Sentinels](#5.5).

**Sources:** [src/openai/_utils/_transform.py:1-458]()

## Architecture Overview

The transformation pipeline consists of five main components:

| Component | Functions | Purpose |
|-----------|-----------|---------|
| **Entry Points** | `transform()`, `async_transform()`, `maybe_transform()`, `async_maybe_transform()` | Public API for initiating transformations [src/openai/_utils/_transform.py:78-317]() |
| **Recursive Processor** | `_transform_recursive()`, `_async_transform_recursive()` | Core logic that handles nested data structures [src/openai/_utils/_transform.py:154-233](), [src/openai/_utils/_transform.py:320-399]() |
| **Key Transformer** | `_maybe_transform_key()` | Applies alias metadata to dictionary keys [src/openai/_utils/_transform.py:131-147]() |
| **Data Formatter** | `_format_data()`, `_async_format_data()` | Converts values based on format specifications [src/openai/_utils/_transform.py:236-260](), [src/openai/_utils/_transform.py:402-426]() |
| **TypedDict Handler** | `_transform_typeddict()`, `_async_transform_typeddict()` | Processes TypedDict with type hints [src/openai/_utils/_transform.py:263-281](), [src/openai/_utils/_transform.py:429-447]() |

### Data Flow Diagram

```mermaid
graph TB
    subgraph "Public API"
        transform["transform()"]
        async_transform["async_transform()"]
        maybe_transform["maybe_transform()"]
        async_maybe_transform["async_maybe_transform()"]
    end
    
    subgraph "Type Inspection"
        _get_annotated_type["_get_annotated_type()"]
        strip_annotated["strip_annotated_type()"]
        get_origin_fn["get_origin()"]
    end
    
    subgraph "Core Processing"
        _transform_recursive["_transform_recursive()"]
        _async_transform_recursive["_async_transform_recursive()"]
    end
    
    subgraph "Specialized Handlers"
        _maybe_transform_key["_maybe_transform_key()"]
        _transform_typeddict["_transform_typeddict()"]
        _async_transform_typeddict["_async_transform_typeddict()"]
        _format_data["_format_data()"]
        _async_format_data["_async_format_data()"]
    end
    
    subgraph "Metadata"
        PropertyInfo["PropertyInfo class"]
    end
    
    transform --> _transform_recursive
    async_transform --> _async_transform_recursive
    maybe_transform --> transform
    async_maybe_transform --> async_transform
    
    _transform_recursive --> _get_annotated_type
    _transform_recursive --> strip_annotated
    _transform_recursive --> get_origin_fn
    _transform_recursive --> _transform_typeddict
    _transform_recursive --> _format_data
    _transform_recursive --> _maybe_transform_key
    
    _async_transform_recursive --> _get_annotated_type
    _async_transform_recursive --> strip_annotated
    _async_transform_recursive --> get_origin_fn
    _async_transform_recursive --> _async_transform_typeddict
    _async_transform_recursive --> _async_format_data
    _async_transform_recursive --> _maybe_transform_key
    
    _transform_typeddict --> _maybe_transform_key
    _transform_typeddict --> _transform_recursive
    _async_transform_typeddict --> _maybe_transform_key
    _async_transform_typeddict --> _async_transform_recursive
    
    PropertyInfo -.metadata.-> _maybe_transform_key
    PropertyInfo -.metadata.-> _format_data
    PropertyInfo -.metadata.-> _async_format_data
```

**Sources:** [src/openai/_utils/_transform.py:78-447]()

## Entry Point Functions

### transform() and maybe_transform()

The `transform()` function is the synchronous entry point that accepts arbitrary data and an expected type annotation, returning transformed data [src/openai/_utils/_transform.py:92-112]().

```python
def transform(data: _T, expected_type: object) -> _T
```

The `maybe_transform()` wrapper handles the case where `data` is `None`, returning `None` without transformation [src/openai/_utils/_transform.py:78-88]().

```python
def maybe_transform(data: object, expected_type: object) -> Any | None
```

**Sources:** [src/openai/_utils/_transform.py:78-112]()

### async_transform() and async_maybe_transform()

The asynchronous variants provide identical semantics but use non-blocking I/O for file operations [src/openai/_utils/_transform.py:284-317]().

```python
async def async_transform(data: _T, expected_type: object) -> _T
async def async_maybe_transform(data: object, expected_type: object) -> Any | None
```

The async path uses `anyio.Path` for non-blocking file reads when encoding files to base64, while the sync path uses standard `pathlib.Path.read_bytes()` [src/openai/_utils/_transform.py:402-426]().

**Sources:** [src/openai/_utils/_transform.py:284-317](), [src/openai/_utils/_transform.py:402-426]()

## Core Transformation Logic

### _transform_recursive()

The `_transform_recursive()` function implements the core recursive transformation algorithm [src/openai/_utils/_transform.py:154-233](). It processes data based on type annotations, handling various Python type constructs:

| Type Pattern | Behavior |
|--------------|----------|
| `TypedDict` | Delegates to `_transform_typeddict()` for key aliasing and recursive value transformation [src/openai/_utils/_transform.py:179-180]() |
| `dict` | Recursively transforms values using the dictionary's value type annotation [src/openai/_utils/_transform.py:182-184]() |
| `List[T]`, `Iterable[T]`, `Sequence[T]` | Recursively transforms each element [src/openai/_utils/_transform.py:186-209]() |
| `Union[T1, T2, ...]` | Applies transformation against all union variants [src/openai/_utils/_transform.py:211-218]() |
| `pydantic.BaseModel` | Converts to dictionary using `model_dump()` with `exclude_unset=True` [src/openai/_utils/_transform.py:220-221]() |
| Annotated types with `PropertyInfo` | Applies format transformations (ISO 8601, base64, custom) [src/openai/_utils/_transform.py:223-233]() |

The function accepts two type parameters:
- `annotation`: The direct type annotation (may be wrapped in `Required[]`, `Annotated[]`, etc.)
- `inner_type`: The unwrapped type for container elements (defaults to `annotation`)

**Sources:** [src/openai/_utils/_transform.py:154-233](), [src/openai/_utils/_transform.py:320-399]()

### Type Stripping and Inspection

Before processing, the function strips metadata wrappers:

1. `strip_annotated_type()` unwraps `Required[Annotated[T, ...]]` to `T` [src/openai/_utils/_typing.py:75-80]().
2. `get_origin()` extracts the base type from generic types (e.g., `list` from `List[int]`) [src/openai/_utils/_transform.py:178]().
3. Type-checking predicates (`is_typeddict()`, `is_mapping()`, `is_list_type()`, etc.) determine handling strategy [src/openai/_utils/_transform.py:179-192]().

**Sources:** [src/openai/_utils/_transform.py:177-178](), [src/openai/_utils/_typing.py:74-80]()

### Performance Optimizations

The `_no_transform_needed()` function identifies types that require no transformation (`int`, `float`), allowing the pipeline to skip recursive processing for performance [src/openai/_utils/_transform.py:150-151]().

```python
def _no_transform_needed(annotation: type) -> bool:
    return annotation == float or annotation == int
```

**Sources:** [src/openai/_utils/_transform.py:150-151](), [src/openai/_utils/_transform.py:200-207]()

## Key Transformation

### _maybe_transform_key()

The `_maybe_transform_key()` function applies alias metadata to dictionary keys [src/openai/_utils/_transform.py:131-147](). It extracts `PropertyInfo` from annotated types and returns the aliased key name:

```python
def _maybe_transform_key(key: str, type_: type) -> str
```

**Process:**
1. Call `_get_annotated_type()` to check for `Annotated[]` wrapper [src/openai/_utils/_transform.py:136]().
2. Extract annotations (ignoring first argument, which is the actual type) [src/openai/_utils/_transform.py:142]().
3. Find first `PropertyInfo` instance with non-None `alias` [src/openai/_utils/_transform.py:143-145]().
4. Return `alias` if found, otherwise return original `key` [src/openai/_utils/_transform.py:147]().

The `_get_annotated_type()` helper handles `Required[Annotated[T, ...]]` by unwrapping the `Required` first, then checking for `Annotated` [src/openai/_utils/_transform.py:121-126]().

**Sources:** [src/openai/_utils/_transform.py:131-147](), [src/openai/_utils/_transform.py:115-128]()

## Data Formatting

### _format_data()

The `_format_data()` function applies format-specific transformations based on `PropertyInfo.format` [src/openai/_utils/_transform.py:236-260]():

| Format | Input Types | Output | Implementation |
|--------|-------------|--------|----------------|
| `"iso8601"` | `datetime`, `date` | ISO 8601 string | `data.isoformat()` [src/openai/_utils/_transform.py:241-242]() |
| `"custom"` | `datetime`, `date` | Custom format string | `data.strftime(format_template)` [src/openai/_utils/_transform.py:244-245]() |
| `"base64"` | `pathlib.Path`, `IO[bytes]` | Base64-encoded string | `base64.b64encode(binary).decode("ascii")` [src/openai/_utils/_transform.py:259]() |

**Base64 Processing:**
- For `pathlib.Path`: reads bytes using `path.read_bytes()` [src/openai/_utils/_transform.py:250]()
- For `IO[bytes]`: reads using `io.read()` [src/openai/_utils/_transform.py:252]()
- For `StringIO`: encodes string to bytes before encoding [src/openai/_utils/_transform.py:254-255]()

**Sources:** [src/openai/_utils/_transform.py:236-260]()

### _async_format_data()

The async variant uses `anyio.Path(data).read_bytes()` for non-blocking file I/O when encoding `pathlib.Path` instances [src/openai/_utils/_transform.py:416-417](). All other logic is identical to the synchronous version.

**Sources:** [src/openai/_utils/_transform.py:402-426]()

## TypedDict Processing

### _transform_typeddict()

The `_transform_typeddict()` function processes TypedDict mappings [src/openai/_utils/_transform.py:263-281]() by:

1. Extracting type hints using `get_type_hints(expected_type, include_extras=True)` [src/openai/_utils/_transform.py:265]().
2. Iterating over input dictionary items [src/openai/_utils/_transform.py:269]().
3. Filtering out `NotGiven` and `Omit` sentinel values using `is_given()` [src/openai/_utils/_transform.py:270]().
4. For each present value:
   - Look up type annotation [src/openai/_utils/_transform.py:275]().
   - Apply `_maybe_transform_key()` for aliasing [src/openai/_utils/_transform.py:276]().
   - Recursively transform value using `_transform_recursive()` [src/openai/_utils/_transform.py:278]().
5. Return transformed dictionary [src/openai/_utils/_transform.py:281]().

**Sentinel Handling:**
- `NotGiven` values are excluded (distinguishes "not provided" from "explicitly None") [src/openai/_utils/_utils.py:160-161]().
- `Omit` values are excluded (explicitly removes default values) [src/openai/_utils/_utils.py:160-161]().

**Sources:** [src/openai/_utils/_transform.py:263-281](), [src/openai/_utils/_transform.py:429-447](), [src/openai/_utils/_utils.py:160-161]()

## Transformation Flow Diagram

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Entry as "transform() / async_transform()"
    participant Recursive as "_transform_recursive()"
    participant TypeInspect as "Type Inspection"
    participant KeyXform as "_maybe_transform_key()"
    participant FormatData as "_format_data()"
    participant TypedDictXform as "_transform_typeddict()"
    
    User->>Entry: "data={'account_name': 'Alice',<br/>'created_at': datetime(...),<br/>'avatar': Path('image.png')}"
    Entry->>Recursive: "annotation=MyParams"
    
    Recursive->>TypeInspect: "strip_annotated_type()"
    TypeInspect-->>Recursive: "MyParams (TypedDict)"
    
    Recursive->>TypedDictXform: "data, MyParams"
    
    loop For each key, value in data
        TypedDictXform->>TypedDictXform: "is_given(value)?"
        
        TypedDictXform->>KeyXform: "key='account_name', type_=Annotated[str, PropertyInfo(alias='accountName')]"
        KeyXform-->>TypedDictXform: "'accountName'"
        
        TypedDictXform->>Recursive: "value='Alice', annotation=Annotated[str, ...]"
        Recursive-->>TypedDictXform: "'Alice'"
        
        TypedDictXform->>KeyXform: "key='created_at', type_=Annotated[datetime, PropertyInfo(format='iso8601')]"
        KeyXform-->>TypedDictXform: "'created_at'"
        
        TypedDictXform->>Recursive: "value=datetime(...), annotation=Annotated[datetime, PropertyInfo(format='iso8601')]"
        Recursive->>FormatData: "data=datetime(...), format='iso8601'"
        FormatData-->>Recursive: "'2023-02-23T14:16:36.337692+00:00'"
        Recursive-->>TypedDictXform: "'2023-02-23T14:16:36.337692+00:00'"
        
        TypedDictXform->>KeyXform: "key='avatar', type_=Annotated[Path, PropertyInfo(format='base64')]"
        KeyXform-->>TypedDictXform: "'avatar'"
        
        TypedDictXform->>Recursive: "value=Path('image.png'), annotation=Annotated[Path, PropertyInfo(format='base64')]"
        Recursive->>FormatData: "data=Path('image.png'), format='base64'"
        FormatData->>FormatData: "path.read_bytes()"
        FormatData->>FormatData: "base64.b64encode()"
        FormatData-->>Recursive: "'iVBORw0KGgo...'"
        Recursive-->>TypedDictXform: "'iVBORw0KGgo...'"
    end
    
    TypedDictXform-->>Recursive: "{'accountName': 'Alice',<br/>'created_at': '2023-02-23T14:16:36.337692+00:00',<br/>'avatar': 'iVBORw0KGgo...'}"
    Recursive-->>Entry: "transformed data"
    Entry-->>User: "transformed data"
```

**Sources:** [src/openai/_utils/_transform.py:78-281]()

## Code Entity Mapping

```mermaid
graph TB
    subgraph "User Data Layer"
        UserDict["Python dict<br/>{snake_case: values}"]
        UserDateTime["datetime objects"]
        UserPath["pathlib.Path"]
        UserModel["pydantic.BaseModel"]
    end
    
    subgraph "Type Annotation Layer"
        TypedDictType["TypedDict with<br/>Annotated fields"]
        PropertyInfoMeta["PropertyInfo metadata<br/>alias, format, format_template"]
        RequiredWrapper["Required[] wrapper"]
    end
    
    subgraph "Transform Functions"
        TransformEntry["transform()<br/>maybe_transform()"]
        AsyncTransformEntry["async_transform()<br/>async_maybe_transform()"]
        TransformRecursive["_transform_recursive()"]
        AsyncTransformRecursive["_async_transform_recursive()"]
    end
    
    subgraph "Key Processing"
        GetAnnotatedType["_get_annotated_type()"]
        MaybeTransformKey["_maybe_transform_key()"]
    end
    
    subgraph "Value Processing"
        TransformTypedDict["_transform_typeddict()"]
        AsyncTransformTypedDict["_async_transform_typeddict()"]
        FormatData["_format_data()"]
        AsyncFormatData["_async_format_data()"]
    end
    
    subgraph "Type Utilities"
        StripAnnotated["strip_annotated_type()"]
        IsTypedDict["is_typeddict()"]
        IsMapping["is_mapping()"]
        IsGiven["is_given()"]
        GetOrigin["get_origin()"]
    end
    
    subgraph "Format Operations"
        IsoFormat["datetime.isoformat()"]
        Strftime["datetime.strftime()"]
        Base64Encode["base64.b64encode()"]
        PathReadBytes["pathlib.Path.read_bytes()<br/>anyio.Path.read_bytes()"]
    end
    
    subgraph "Output Data Layer"
        APIDict["JSON-serializable dict<br/>{camelCase: values}"]
        ISOString["ISO 8601 strings"]
        Base64String["base64 strings"]
    end
    
    UserDict --> TransformEntry
    UserDateTime --> TransformEntry
    UserPath --> TransformEntry
    UserModel --> TransformEntry
    
    TypedDictType --> TransformEntry
    PropertyInfoMeta --> MaybeTransformKey
    PropertyInfoMeta --> FormatData
    RequiredWrapper --> GetAnnotatedType
    
    TransformEntry --> TransformRecursive
    AsyncTransformEntry --> AsyncTransformRecursive
    
    TransformRecursive --> StripAnnotated
    TransformRecursive --> GetOrigin
    TransformRecursive --> IsTypedDict
    TransformRecursive --> IsMapping
    TransformRecursive --> TransformTypedDict
    
    TransformTypedDict --> IsGiven
    TransformTypedDict --> MaybeTransformKey
    TransformTypedDict --> TransformRecursive
    
    AsyncTransformRecursive --> AsyncTransformTypedDict
    AsyncTransformTypedDict --> AsyncTransformRecursive
    
    MaybeTransformKey --> GetAnnotatedType
    GetAnnotatedType --> StripAnnotated
    
    TransformRecursive --> FormatData
    AsyncTransformRecursive --> AsyncFormatData
    
    FormatData --> IsoFormat
    FormatData --> Strftime
    FormatData --> Base64Encode
    FormatData --> PathReadBytes
    
    AsyncFormatData --> IsoFormat
    AsyncFormatData --> Strftime
    AsyncFormatData --> Base64Encode
    AsyncFormatData --> PathReadBytes
    
    TransformRecursive --> APIDict
    FormatData --> ISOString
    FormatData --> Base64String
    
    APIDict --> ISOString
    APIDict --> Base64String
```

**Sources:** [src/openai/_utils/_transform.py:1-458](), [src/openai/_utils/_utils.py:133-134](), [src/openai/_utils/_typing.py:74-80]()

## Practical Examples

### Example 1: Key Aliasing

**Input:**
```python
class Params(TypedDict):
    account_holder_name: Annotated[str, PropertyInfo(alias='accountHolderName')]

transform({'account_holder_name': 'Robert'}, Params)
```

**Output:**
```python
{'accountHolderName': 'Robert'}
```

**Sources:** [tests/test_transform.py:40-47]()

### Example 2: DateTime Formatting

**Input:**
```python
class DatetimeParams(TypedDict):
    created_at: Annotated[datetime, PropertyInfo(format='iso8601')]

dt = datetime.fromisoformat('2023-02-23T14:16:36.337692+00:00')
transform({'created_at': dt}, DatetimeParams)
```

**Output:**
```python
{'created_at': '2023-02-23T14:16:36.337692+00:00'}
```

**Sources:** [tests/test_transform.py:164-206]()

### Example 3: Sentinel Value Filtering

**Input:**
```python
from openai._types import not_given, omit

class Params(TypedDict):
    foo_bar: Annotated[str, PropertyInfo(alias='fooBar')]

transform({'foo_bar': not_given}, Params)  # Returns {}
transform({'foo_bar': omit}, Params)       # Returns {}
transform({'foo_bar': None}, Params)       # Returns {'fooBar': None}
```

**Sources:** [tests/test_transform.py:449-460](), [src/openai/_utils/_transform.py:270-273]()

---

# Page: PropertyInfo and Field Metadata

# PropertyInfo and Field Metadata

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



The `PropertyInfo` class provides declarative field-level transformation metadata used by the SDK's data transformation pipeline. It controls how Python field names and values are transformed when preparing API requests.

For the overall transformation pipeline that consumes this metadata, see [Data Transformation Pipeline](6.1). For type coercion during response parsing, see [Type Coercion and Construction](6.3).

---

## Overview

`PropertyInfo` enables declarative transformation rules through Python's `Annotated` type system:

- **Field aliasing**: Maps Python `snake_case` names to API `camelCase` names.
- **Format specifications**: Converts `datetime`, `date`, or file objects to API-compatible strings (e.g., ISO 8601 or Base64).
- **Discriminator metadata**: Supports discriminated union type resolution during serialization.

`PropertyInfo` instances attach to type annotations and are extracted by transformation functions (`transform()`, `async_transform()`) during request serialization.

### Role in Transformation Pipeline

```mermaid
flowchart TD
    UserCode["User Code<br/>{'account_holder_name': 'value'}"]
    TypeDef["TypedDict with<br/>PropertyInfo annotations"]
    Transform["maybe_transform()<br/>_transform_recursive()"]
    KeyTransform["_maybe_transform_key()<br/>Extract alias"]
    FormatData["_format_data()<br/>Apply format"]
    APIRequest["API Request<br/>{'accountHolderName': 'value'}"]
    
    UserCode --> Transform
    TypeDef -.metadata.-> KeyTransform
    Transform --> KeyTransform
    Transform --> FormatData
    TypeDef -.metadata.-> FormatData
    KeyTransform --> APIRequest
    FormatData --> APIRequest
```

**Sources:** [src/openai/_utils/_transform.py:44-76](), [src/openai/_utils/_transform.py:78-113]()

---

## PropertyInfo Class Definition

### Attributes

```mermaid
classDiagram
    class PropertyInfo {
        +str|None alias
        +PropertyFormat|None format
        +str|None format_template
        +str|None discriminator
        +__init__(alias, format, format_template, discriminator)
        +__repr__() str
    }
    
    class PropertyFormat {
        <<enumeration>>
        iso8601
        base64
        custom
    }
    
    PropertyInfo --> PropertyFormat : uses
```

| Attribute | Type | Purpose |
|-----------|------|---------|
| `alias` | `str \| None` | Alternative field name to use in serialized output. |
| `format` | `PropertyFormat \| None` | Formatting strategy for the field value (e.g., ISO8601). |
| `format_template` | `str \| None` | Template string for custom datetime formatting via `strftime`. |
| `discriminator` | `str \| None` | Discriminator field name for union types. |

The `PropertyFormat` type is defined as:
`PropertyFormat = Literal["iso8601", "base64", "custom"]` [src/openai/_utils/_transform.py:41-41]()

**Sources:** [src/openai/_utils/_transform.py:41-76]()

---

## Field Aliasing

Field aliasing allows Python code to use idiomatic `snake_case` field names while transforming them to the API's naming conventions (typically `camelCase`).

### Transformation Flow

```mermaid
flowchart LR
    Input["{'account_holder_name': 'Robert'}"]
    GetTypeHints["get_type_hints()<br/>with include_extras=True"]
    ExtractAnnotated["_get_annotated_type()<br/>Check for Annotated wrapper"]
    GetArgs["get_args(annotated_type)<br/>[str, PropertyInfo(...)]"]
    ExtractAlias["PropertyInfo.alias<br/>'accountHolderName'"]
    Output["{'accountHolderName': 'Robert'}"]
    
    Input --> GetTypeHints
    GetTypeHints --> ExtractAnnotated
    ExtractAnnotated --> GetArgs
    GetArgs --> ExtractAlias
    ExtractAlias --> Output
```

### Implementation

The `_maybe_transform_key()` function at [src/openai/_utils/_transform.py:131-148]() extracts aliases:

1. Calls `_get_annotated_type(type_)` to check for `Annotated` wrapper.
2. If found, calls `get_args(annotated_type)[1:]` to extract metadata (index 0 is the base type).
3. Iterates annotations to find `PropertyInfo` instances.
4. Returns `PropertyInfo.alias` if set, otherwise returns the original key unchanged.

The `_transform_typeddict()` function at [src/openai/_utils/_transform.py:263-282]() obtains type hints using `_get_type_hints(expected_type, include_extras=True)`, which is critical for preserving `Annotated` metadata.

**Sources:** [src/openai/_utils/_transform.py:131-148](), [src/openai/_utils/_transform.py:263-282](), [src/openai/_utils/_transform.py:450-458]()

### Usage Example

```python
class MyParams(TypedDict):
    account_holder_name: Annotated[str, PropertyInfo(alias='accountHolderName')]

# Input: {'account_holder_name': 'Robert'}
# Output: {'accountHolderName': 'Robert'}
```

**Sources:** [src/openai/_utils/_transform.py:48-52](), [tests/test_transform.py:40-47]()

---

## Format Specifications

The `format` attribute in `PropertyInfo` controls how field values are serialized.

### ISO 8601 Datetime Formatting

```mermaid
graph LR
    DateTime["datetime/date object"]
    CheckFormat["_format_data()<br/>Check format == 'iso8601'"]
    CheckType["isinstance(data,<br/>(date, datetime))"]
    Isoformat["data.isoformat()"]
    Output["'2023-02-23T14:16:36.337692+00:00'"]
    
    DateTime --> CheckFormat
    CheckFormat --> CheckType
    CheckType -->|True| Isoformat
    Isoformat --> Output
```

**Behavior at [src/openai/_utils/_transform.py:237-243]():**
- Checks `isinstance(data, (date, datetime))`.
- If `format_ == "iso8601"`, calls `data.isoformat()`.
- Preserves timezone information if present.

**Sources:** [src/openai/_utils/_transform.py:236-243]()

### Base64 File Encoding

Automatically encodes file content to base64 for JSON-embedded file transmission (e.g., for DALL-E image edits or specific Vision inputs):

| Input Type | Processing |
|------------|------------|
| `pathlib.Path` | Reads file bytes via `read_bytes()`, encodes to base64. |
| `io.IOBase` | Reads stream content via `read()`, encodes to base64. |
| `str` | Passes through unchanged (assumed pre-encoded). |

**Implementation at [src/openai/_utils/_transform.py:244-260]():**
1. Checks `format_ == "base64"` and `is_base64_file_input(data)`.
2. If `pathlib.Path`: reads bytes via `data.read_bytes()`.
3. If `io.IOBase`: reads via `data.read()`, converts str to bytes if needed.
4. Calls `base64.b64encode(binary).decode("ascii")`.

**Sync vs Async:**
- Synchronous `_format_data()` uses blocking `pathlib.Path.read_bytes()` [src/openai/_utils/_transform.py:248]().
- Asynchronous `_async_format_data()` uses `anyio.Path(data).read_bytes()` [src/openai/_utils/_transform.py:414]().

**Sources:** [src/openai/_utils/_transform.py:244-260](), [src/openai/_utils/_transform.py:410-426]()

---

## Integration with Annotated Types

`PropertyInfo` is used as metadata in Python's `Annotated` type construct.

### Type Structure Unwrapping

The `_get_annotated_type()` function at [src/openai/_utils/_transform.py:116-129]():
- Checks `is_required_type(type_)` via `get_origin(type_) == Required` [src/openai/_utils/_typing.py:45]().
- If true, unwraps via `get_args(type_)[0]` to strip `Required[]`.
- Checks `is_annotated_type(type_)` via `get_origin(type_) == Annotated` [src/openai/_utils/_typing.py:22]().
- Returns the `Annotated` type or `None`.

**Performance:** Decorated with `@lru_cache(maxsize=8096)` [src/openai/_utils/_transform.py:115]() for repeated type lookups.

**Sources:** [src/openai/_utils/_transform.py:115-129](), [src/openai/_utils/_typing.py:21-46]()

---

## Transformation Pipeline Integration

`PropertyInfo` metadata is consumed by the recursive transformation pipeline.

### Transformation Sequence

```mermaid
sequenceDiagram
    participant Input as "{'foo_bar': datetime(...)}"
    participant GetHints as _get_type_hints()
    participant Transform as _transform_recursive()
    participant GetAnnotated as _get_annotated_type()
    participant GetArgs as get_args()
    participant KeyXform as _maybe_transform_key()
    participant FormatData as _format_data()
    participant Output as "{'fooBar': '2023-...'}"
    
    Input->>GetHints: Expected TypedDict type
    GetHints-->>Transform: {field: Annotated[...]}
    
    loop For each field
        Transform->>KeyXform: field name + type
        KeyXform->>GetAnnotated: Check for Annotated
        GetAnnotated-->>KeyXform: Annotated type or None
        KeyXform->>GetArgs: Extract metadata
        GetArgs-->>KeyXform: [base_type, PropertyInfo(...)]
        KeyXform-->>Transform: Transformed key
        
        Transform->>FormatData: value + PropertyInfo
        FormatData->>GetAnnotated: Get format metadata
        GetAnnotated-->>FormatData: PropertyInfo.format
        FormatData->>FormatData: Apply transformation
        FormatData-->>Transform: Formatted value
    end
    
    Transform->>Output: Final dictionary
```

### Key Functions

| Function | Purpose | Location |
|----------|---------|----------|
| `transform()` | Entry point for synchronous transformation. | [src/openai/_utils/_transform.py:92-113]() |
| `_transform_recursive()` | Handles nested structures (dict, list, union). | [src/openai/_utils/_transform.py:154-234]() |
| `_maybe_transform_key()` | Extracts alias from `PropertyInfo` metadata. | [src/openai/_utils/_transform.py:131-148]() |
| `_format_data()` | Applies format transformation logic (ISO 8601, Base64). | [src/openai/_utils/_transform.py:236-261]() |
| `_get_annotated_type()` | Unwraps `Required`/`Annotated` metadata. | [src/openai/_utils/_transform.py:116-129]() |

**Sources:** [src/openai/_utils/_transform.py:92-282](), [src/openai/_utils/_transform.py:450-458]()

---

## Synchronous vs Asynchronous Processing

The transformation system provides parallel implementations to support both `OpenAI` and `AsyncOpenAI` clients:

| Operation | Sync Function | Async Function |
|-----------|---------------|----------------|
| Entry point | `transform()` [src/openai/_utils/_transform.py:92]() | `async_transform()` [src/openai/_utils/_transform.py:297]() |
| Recursive transform | `_transform_recursive()` [src/openai/_utils/_transform.py:154]() | `_async_transform_recursive()` [src/openai/_utils/_transform.py:320]() |
| Format data | `_format_data()` [src/openai/_utils/_transform.py:236]() | `_async_format_data()` [src/openai/_utils/_transform.py:402]() |

Both implementations share the same metadata extraction logic via `_get_annotated_type()` and `_maybe_transform_key()`. The async version uses `anyio` for non-blocking file reads during Base64 encoding [src/openai/_utils/_transform.py:414]().

**Sources:** [src/openai/_utils/_transform.py:92-447]()

---

## Export and Availability

`PropertyInfo` is exported through the internal utility module for use throughout the SDK:

```python
from openai._utils import PropertyInfo
```

**Sources:** [src/openai/_utils/__init__.py:56-62]()

---

# Page: Type Coercion and Construction

# Type Coercion and Construction

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)

</details>



This page documents the type coercion and construction system used for deserializing API responses and constructing model instances without strict validation. This system enables "loose coercion" where data is transformed into the expected types on a best-effort basis, returning values as-is when coercion is not possible.

---

## Purpose and Scope

The type coercion system serves two primary purposes:

1. **Response Deserialization**: Constructing strongly-typed Pydantic models from raw API response data without triggering validation errors [src/openai/_models.py:494-611]().
2. **Graceful Type Handling**: Allowing mismatched or unexpected data to pass through the system rather than failing, enabling flexibility when the API behavior differs from the specification [tests/test_models.py:19-35]().

This approach is critical for API clients because:
- APIs may return data that doesn't perfectly match the OpenAPI specification [tests/test_models.py:283-303]().
- Forward compatibility is maintained when new fields are added [tests/test_models.py:148-158]().
- Partial or incomplete data can still be represented as model instances [src/openai/_models.py:203-264]().
- Type safety is preserved at the Python level while remaining lenient with API responses [src/openai/_models.py:485-491]().

**Sources**: [src/openai/_models.py:494-611](), [tests/test_models.py:19-35](), [tests/test_models.py:283-303](), [tests/test_models.py:148-158](), [src/openai/_models.py:203-264](), [src/openai/_models.py:485-491]()

---

## Core Functions

### construct_type()

The primary entry point for loose type coercion:

```python
construct_type(*, value: object, type_: object, metadata: Optional[List[Any]] = None) -> object
```

**Behavior**:
- Recursively constructs nested types (models, lists, dicts) [src/openai/_models.py:562-588]().
- Returns the value as-is if coercion is not possible or appropriate [src/openai/_models.py:611]().
- Does not raise validation errors for type mismatches [tests/test_models.py:33-34]().
- Extracts and processes `Annotated` type metadata (e.g., `PropertyInfo`) [src/openai/_models.py:502-505]().

**Key characteristics**:
- **Non-strict**: Unlike `validate_type()`, this function does not enforce type correctness [src/openai/_models.py:494-611]().
- **Recursive**: Processes nested structures (models within models, lists of models, etc.) [src/openai/_models.py:562-588]().
- **Metadata-aware**: Respects `PropertyInfo` annotations for discriminated unions [src/openai/_models.py:545-551]().
- **Type-preserving**: Maintains the original value when coercion is not applicable [src/openai/_models.py:611]().

**Sources**: [src/openai/_models.py:494-611](), [src/openai/_models.py:562-588](), [tests/test_models.py:33-34](), [src/openai/_models.py:502-505](), [src/openai/_models.py:545-551]()

### construct_type_unchecked()

Type-safe wrapper for `construct_type()`:

```python
construct_type_unchecked(*, value: object, type_: type[_T]) -> _T
```

Returns a value cast to the expected type, providing better type checker support [src/openai/_models.py:485-491](). The "unchecked" name indicates that the cast is not guaranteed to be accurate—the returned value may not actually match the declared type if coercion failed.

**Sources**: [src/openai/_models.py:485-491]()

### build()

Higher-level helper for constructing `BaseModel` instances:

```python
build(base_model_cls: Callable[P, _BaseModelT], *args: P.args, **kwargs: P.kwargs) -> _BaseModelT
```

Provides type-safe construction of `BaseModel` instances using keyword arguments only [src/openai/_models.py:462-482](). This wrapper ensures that the construction call matches the model's field signatures at the type-checking level.

**Sources**: [src/openai/_models.py:462-482]()

### validate_type()

Strict validation alternative:

```python
validate_type(*, type_: type[_T], value: object) -> _T
```

Unlike `construct_type()`, this function performs strict validation and raises errors if the value doesn't match the expected type [src/openai/_models.py:744-749]().

**Sources**: [src/openai/_models.py:744-749]()

---

## Construction vs Validation

The library provides two distinct approaches for handling typed data:

### Type Processing Flow
```mermaid
graph TB
    Input["Raw API Response Data"]
    
    ConstructPath["construct_type()"]
    ValidatePath["validate_type()"]
    
    ConstructCheck{"Type matches?"}
    ValidateCheck{"Type matches?"}
    
    ConstructSuccess["Constructed Model"]
    ConstructFallback["Original Value<br/>(unchanged)"]
    ValidateSuccess["Validated Model"]
    ValidateError["Raises Exception"]
    
    Input --> ConstructPath
    Input --> ValidatePath
    
    ConstructPath --> ConstructCheck
    ValidatePath --> ValidateCheck
    
    ConstructCheck -->|"Yes"| ConstructSuccess
    ConstructCheck -->|"No"| ConstructFallback
    
    ValidateCheck -->|"Yes"| ValidateSuccess
    ValidateCheck -->|"No"| ValidateError
```

**When construct_type() is used**:
- Deserializing API responses via `BaseModel.construct()` [src/openai/_models.py:203-264]().
- Building models from potentially incomplete data [tests/test_models.py:148-158]().
- Parsing data where the API may not match the spec exactly [tests/test_models.py:283-303]().

**When validate_type() is used**:
- User-provided input that must conform to strict types [src/openai/_models.py:744-749]().
- Union type resolution when discriminator matching is attempted [src/openai/_models.py:530-535]().

**Sources**: [src/openai/_models.py:494-749](), [src/openai/_models.py:203-264](), [tests/test_models.py:148-158](), [tests/test_models.py:283-303](), [src/openai/_models.py:744-749](), [src/openai/_models.py:530-535]()

---

## Type Handling

### BaseModel Construction

When the target type is a `BaseModel` or `GenericModel` subclass, construction follows special rules:

### BaseModel Dispatch Logic
```mermaid
graph TB
    Start["construct_type(value, type_=MyModel)"]
    IsBaseModel{"Is type a<br/>BaseModel?"}
    
    IsList{"Is value<br/>a list?"}
    IsMapping{"Is value<br/>a mapping?"}
    
    ConstructEach["Construct each entry:<br/>MyModel.construct(**entry)"]
    ConstructSingle["MyModel.construct(**value)"]
    ReturnAsIs["Return value as-is"]
    
    Start --> IsBaseModel
    IsBaseModel -->|"Yes"| IsList
    IsBaseModel -->|"No"| OtherHandling["Other type handling..."]
    
    IsList -->|"Yes"| ConstructEach
    IsList -->|"No"| IsMapping
    
    IsMapping -->|"Yes"| ConstructSingle
    IsMapping -->|"No"| ReturnAsIs
```

**List of models**: If the value is a list and each entry is a mapping, each entry is constructed separately via `MyModel.construct(**entry)` [src/openai/_models.py:569-581]().

**Single model**: If the value is a mapping (dict), it's passed directly to `construct()` [src/openai/_models.py:575-581]().

**Sources**: [src/openai/_models.py:569-581](), [tests/test_models.py:54-71]()

### Union Type Resolution

Union types are handled with a fallback strategy: try each variant in order until one succeeds [src/openai/_models.py:525-560]().

#### Basic Union Resolution

```mermaid
graph TB
    Start["construct_type(value, Union[A, B, C])"]
    
    TryValidate["Try validate_type()<br/>with full union"]
    ValidateSuccess{"Succeeds?"}
    
    CheckDiscriminator{"Has discriminator<br/>metadata?"}
    ResolveDiscriminated["Resolve discriminated<br/>union variant"]
    
    TryVariants["Try construct_type()<br/>for each variant"]
    VariantSuccess{"Any variant<br/>succeeds?"}
    
    ReturnValidated["Return validated result"]
    ReturnDiscriminated["Return discriminated result"]
    ReturnFirstSuccess["Return first successful variant"]
    RaiseError["Raise RuntimeError"]
    
    Start --> TryValidate
    TryValidate --> ValidateSuccess
    
    ValidateSuccess -->|"Yes"| ReturnValidated
    ValidateSuccess -->|"No"| CheckDiscriminator
    
    CheckDiscriminator -->|"Yes"| ResolveDiscriminated
    CheckDiscriminator -->|"No"| TryVariants
    
    ResolveDiscriminated --> ReturnDiscriminated
    
    TryVariants --> VariantSuccess
    VariantSuccess -->|"Yes"| ReturnFirstSuccess
    VariantSuccess -->|"No"| RaiseError
```

**Sources**: [src/openai/_models.py:525-560]()

#### Discriminated Unions

Discriminated unions use a special field to determine which variant to construct, even when the data doesn't perfectly match the expected type [src/openai/_models.py:614-720]().

**Metadata specification**:
```python
Annotated[Union[A, B], PropertyInfo(discriminator="type")]
```

**Resolution algorithm**:
1. Build discriminator metadata via `_build_discriminated_union_meta()` (or retrieve from `DISCRIMINATOR_CACHE`) [src/openai/_models.py:545-551]().
2. Extract the discriminator field value from the input data [src/openai/_models.py:614-720]().
3. Look up the corresponding variant type in the mapping [src/openai/_models.py:614-720]().
4. Construct that specific variant, bypassing the fallback loop [src/openai/_models.py:551]().

**Caching**: Discriminator details are cached in `DISCRIMINATOR_CACHE` (a `WeakKeyDictionary`) to avoid rebuilding the mapping on every call [src/openai/_models.py:614-615]().

**Sources**: [src/openai/_models.py:545-551](), [src/openai/_models.py:614-720](), [tests/test_models.py:657-833]()

### Container Types

#### Dictionary Construction
For `Dict[str, T]` types, each value is recursively constructed via `construct_type` [src/openai/_models.py:562-567]().

#### List Construction
For `List[T]` types, each element is recursively constructed [src/openai/_models.py:583-588](). If `inner_type` is `float` or `int`, transformation is skipped for performance [src/openai/_models.py:584-585]().

**Sources**: [src/openai/_models.py:562-567](), [src/openai/_models.py:583-588]()

### Primitive Type Coercion

#### Integer to Float
Special handling exists for safely coercing integers to floats only when the conversion is lossless (e.g., within 2^53 range) [src/openai/_models.py:590-597]().

#### Date and DateTime Parsing
String values are automatically parsed to `datetime` or `date` objects using `parse_datetime` or `parse_date` [src/openai/_models.py:599-609](). If parsing fails, the original value is returned unchanged [src/openai/_models.py:603, 609]().

**Sources**: [src/openai/_models.py:590-597](), [src/openai/_models.py:599-609](), [tests/test_models.py:423-441](), [tests/test_models.py:453-469]()

---

## BaseModel.construct() Override

The library overrides Pydantic's `construct()` method to provide custom construction logic that handles aliases and nested construction [src/openai/_models.py:203-264]().

### BaseModel.construct() Logic
```mermaid
graph TB
    Call["BaseModel.construct(field1=val1, field2=val2)"]
    
    InitModel["Create new instance:<br/>m = __cls.__new__(__cls__)"]
    InitFields["fields_values = {}"]
    
    IterateFields["For each field in model_fields:"]
    CheckAlias{"Has field alias?"}
    UseAlias["key = field.alias"]
    UseName["key = field.name"]
    
    InValues{"key in values?"}
    ConstructField["Construct field:<br/>_construct_field(value, field)"]
    UseDefault["Use field default"]
    
    StoreField["fields_values[name] = result"]
    
    HandleExtras["Handle extra fields<br/>(not in model_fields)"]
    SetDict["Set __dict__ to fields_values"]
    SetFieldsSet["Set __fields_set__ or<br/>__pydantic_fields_set__"]
    
    Return["Return constructed model"]
    
    Call --> InitModel
    InitModel --> InitFields
    InitFields --> IterateFields
    
    IterateFields --> CheckAlias
    CheckAlias -->|"Yes<br/>(and in values)"| UseAlias
    CheckAlias -->|"No or<br/>not in values"| UseName
    
    UseAlias --> InValues
    UseName --> InValues
    
    InValues -->|"Yes"| ConstructField
    InValues -->|"No"| UseDefault
    
    ConstructField --> StoreField
    UseDefault --> StoreField
    
    StoreField --> IterateFields
    IterateFields -.->|"All fields<br/>processed"| HandleExtras
    
    HandleExtras --> SetDict
    SetDict --> SetFieldsSet
    SetFieldsSet --> Return
```

**Sources**: [src/openai/_models.py:203-264]()

---

## Field Construction with _construct_field()

Individual fields are constructed via the `_construct_field()` helper [src/openai/_models.py:411-423]():

```python
def _construct_field(value: object, field: FieldInfo, key: str) -> object:
    if value is None:
        return field_get_default(field)
    
    # ... type extraction logic ...
    
    return construct_type(value=value, type_=type_, metadata=getattr(field, "metadata", None))
```

**Process**:
1. If the value is `None`, return the field's default value [src/openai/_models.py:412-413]().
2. Extract the field's type annotation (`outer_type_` in v1, `annotation` in v2) [src/openai/_models.py:415-418]().
3. Call `construct_type()` with the field's metadata for `Annotated` types [src/openai/_models.py:423]().

**Sources**: [src/openai/_models.py:411-423]()

---

## Discriminator Caching System

The discriminated union resolution system uses aggressive caching via `DISCRIMINATOR_CACHE` [src/openai/_models.py:614-741]().

**DiscriminatorDetails structure**:

| Field | Type | Purpose |
|-------|------|---------|
| `field_name` | `str` | The discriminator field in the Python model [src/openai/_models.py:619](). |
| `field_alias_from` | `str \| None` | The discriminator field in the API response if an alias is used [src/openai/_models.py:620](). |
| `mapping` | `dict[str, type]` | Maps discriminator values to variant types [src/openai/_models.py:618](). |

**Sources**: [src/openai/_models.py:614-741](), [tests/test_models.py:799-833]()

---

## Extra Fields Handling

The construction system preserves unknown fields (those not defined in the model). In Pydantic v2, these are stored in `__pydantic_extra__` [src/openai/_models.py:237-248](). If the model defines an `extra` field type, extra fields are constructed using that type via `construct_type` [src/openai/_models.py:426-440]().

**Sources**: [src/openai/_models.py:237-248](), [src/openai/_models.py:426-440]()

---

## TypeAliasType Support

Python 3.12+ `TypeAliasType` annotations are unwrapped before processing by `construct_type` [src/openai/_models.py:507-509]().

**Sources**: [src/openai/_models.py:507-509](), [tests/test_models.py:836-849]()

---

# Page: Pydantic Compatibility Layer

# Pydantic Compatibility Layer

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)

</details>



## Purpose and Scope

The Pydantic compatibility layer enables the OpenAI Python library to work seamlessly with both Pydantic v1 and Pydantic v2, which have significant API differences. This layer provides a unified interface through compatibility shims, method aliases, and conditional logic that adapts to the installed Pydantic version at runtime.

This page documents the compatibility infrastructure located in [`src/openai/_compat.py`](). For information about the custom `BaseModel` class that extends Pydantic's base model, see [5.4](). For type coercion and construction utilities, see [6.3]().

---

## Version Detection and Flag

The compatibility layer begins with a single boolean flag that determines all subsequent behavior:

```python
PYDANTIC_V1 = pydantic.VERSION.startswith("1.")
```

This flag is evaluated once at import time by checking the `pydantic.VERSION` string. All compatibility logic throughout the library branches on this flag to select the appropriate API calls, configuration structures, and type handling mechanisms.

**Sources:** [src/openai/_compat.py:20-20]()

---

## Import Compatibility

### Type Utilities

The compatibility layer re-exports type inspection utilities from different locations depending on the Pydantic version. If Pydantic v2 is detected, the SDK falls back to internal implementations in `_utils` to replace utilities removed from Pydantic's public API.

| Function | Pydantic v1 Source | Pydantic v2 Source |
|----------|-------------------|-------------------|
| `get_args` | `pydantic.typing` | `openai._utils` |
| `get_origin` | `pydantic.typing` | `openai._utils` |
| `is_union` | `pydantic.typing` | `openai._utils` |
| `is_literal_type` | `pydantic.typing` | `openai._utils` |
| `is_typeddict` | `pydantic.typing` | `openai._utils` |
| `parse_date` | `pydantic.datetime_parse` | `openai._utils` |
| `parse_datetime` | `pydantic.datetime_parse` | `openai._utils` |

**Sources:** [src/openai/_compat.py:46-65]()

### ConfigDict

Pydantic v2 introduced `ConfigDict` as a typed dictionary for model configuration. For v1 compatibility, the layer sets `ConfigDict = None` when running under Pydantic v1, since the older version uses a nested `Config` class instead.

**Sources:** [src/openai/_compat.py:69-77]()

---

## Method Name Compatibility Shims

Pydantic v2 renamed several core methods. The compatibility layer provides wrapper functions that call the appropriate method for the installed version.

### Model Parsing and Validation

Model Validation Mapping
```mermaid
graph LR
    "UserCode"["User Code"]
    "Shim"["_compat.parse_obj()"]
    "V1"["Pydantic v1<br/>model.parse_obj()"]
    "V2"["Pydantic v2<br/>model.model_validate()"]
    
    "UserCode" --> "Shim"
    "Shim" -->|"PYDANTIC_V1 == True"| "V1"
    "Shim" -->|"PYDANTIC_V1 == False"| "V2"
```

#### parse_obj / model_parse
Maps to the appropriate validation method for dictionary-to-model conversion.
- **Pydantic v1:** `model.parse_obj(value)` [src/openai/_compat.py:82-82]()
- **Pydantic v2:** `model.model_validate(value)` [src/openai/_compat.py:84-84]()

#### model_parse_json
Maps to JSON string parsing.
- **Pydantic v1:** `model.parse_raw(data)` [src/openai/_compat.py:177-177]()
- **Pydantic v2:** `model.model_validate_json(data)` [src/openai/_compat.py:178-178]()

### Model Serialization

#### model_dump
Serializes a model to a dictionary. This shim handles the `mode` parameter (JSON vs Python) which did not exist in v1.
- **Pydantic v1:** Calls `model.dict()`. If `mode="json"` is requested, the SDK relies on its internal `_CustomEncoder` in `openapi_dumps`. [src/openai/_compat.py:163-166]()
- **Pydantic v2:** Calls `model.model_dump(mode=mode, ...)`. [src/openai/_compat.py:152-160]()

#### model_json
Serializes a model to a JSON string.
- **Pydantic v1:** `model.json(indent=...)` [src/openai/_compat.py:130-130]()
- **Pydantic v2:** `model.model_dump_json(indent=...)` [src/openai/_compat.py:131-131]()

#### model_json_schema
Generates a JSON schema.
- **Pydantic v1:** `model.schema()` [src/openai/_compat.py:183-183]()
- **Pydantic v2:** `model.model_json_schema()` [src/openai/_compat.py:184-184]()

**Sources:** [src/openai/_compat.py:80-184](), [src/openai/_utils/_json.py:28-36]()

---

## BaseModel Compatibility Adaptations

The custom `BaseModel` class in [`src/openai/_models.py`]() extends `pydantic.BaseModel` with version-specific adaptations.

### Configuration

Model Configuration Branching
```mermaid
graph TB
    "BaseModel"["openai._models.BaseModel"]
    
    subgraph "Pydantic_v1"
        "V1Config"["class Config(pydantic.BaseConfig):<br/>extra = pydantic.Extra.allow"]
    end
    
    subgraph "Pydantic_v2"
        "V2Config"["model_config: ClassVar[ConfigDict] = <br/>ConfigDict(extra='allow',<br/>defer_build=...)"]
    end
    
    "BaseModel" -->|"PYDANTIC_V1"| "V1Config"
    "BaseModel" -->|"not PYDANTIC_V1"| "V2Config"
```

- **Pydantic v1:** Uses nested `Config` class with `extra` set to `pydantic.Extra.allow`. [src/openai/_models.py:120-121]()
- **Pydantic v2:** Uses `model_config` class variable with `ConfigDict(extra="allow", defer_build=...)`. [src/openai/_models.py:128-130]()

The `defer_build` option in v2 is controlled by the `DEFER_PYDANTIC_BUILD` environment variable to optimize performance by delaying schema generation. [src/openai/_models.py:129-129]()

### model_fields_set Property
Pydantic v2 renamed the internal `__fields_set__` to a public property. The SDK adds a forwards-compatible property for v1.
- **Source:** [src/openai/_models.py:114-118]()

### Representation Methods
For Pydantic v1, the `__repr_args__` method is overridden to exclude internal SDK attributes like `_request_id` from being printed in logs or debuggers.
- **Source:** [src/openai/_models.py:123-126]()

---

## Field and Model Introspection

The compatibility layer provides unified functions to access model metadata.

Field Metadata Access
```mermaid
graph LR
    subgraph "SDK_Unified_Functions"
        "GetFields"["get_model_fields(model)"]
        "GetConfig"["get_model_config(model)"]
        "FieldDefault"["field_get_default(field)"]
        "FieldRequired"["field_is_required(field)"]
    end
    
    subgraph "Pydantic_v1_Internal"
        "V1Fields"["model.__fields__"]
        "V1Config"["model.__config__"]
        "V1Required"["field.required"]
    end
    
    subgraph "Pydantic_v2_Internal"
        "V2Fields"["model.model_fields"]
        "V2Config"["model.model_config"]
        "V2Required"["field.is_required()"]
    end
    
    "GetFields" -.->|"PYDANTIC_V1"| "V1Fields"
    "GetFields" -.->|"not PYDANTIC_V1"| "V2Fields"
    "FieldRequired" -.->|"PYDANTIC_V1"| "V1Required"
    "FieldRequired" -.->|"not PYDANTIC_V1"| "V2Required"
```

#### get_model_fields
Returns the dictionary of fields defined on a model.
- **Pydantic v1:** `model.__fields__` [src/openai/_compat.py:117-118]()
- **Pydantic v2:** `model.model_fields` [src/openai/_compat.py:119-119]()

#### field_get_default
Gets the default value for a field, handling Pydantic's internal "Undefined" sentinels.
- **Pydantic v2:** Converts `PydanticUndefined` to `None` for consistent behavior. [src/openai/_compat.py:97-101]()

**Sources:** [src/openai/_compat.py:87-120]()

---

## GenericModel Handling

Pydantic v1 required a separate `GenericModel` class for generic types. In Pydantic v2, this distinction was removed. The SDK exports a shim `GenericModel` that inherits correctly based on the version.

- **Pydantic v1:** Inherits from `pydantic.generics.GenericModel`. [src/openai/_compat.py:193-196]()
- **Pydantic v2:** Simply inherits from `pydantic.BaseModel`. [src/openai/_compat.py:201-201]()

**Sources:** [src/openai/_compat.py:188-201]()

---

## JSON Serialization Integration

The compatibility layer integrates with the SDK's JSON encoder to ensure Pydantic models are serialized correctly when passed to `httpx` or other IO functions.

```python
class _CustomEncoder(json.JSONEncoder):
    @override
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, pydantic.BaseModel):
            return model_dump(o, exclude_unset=True, mode="json", by_alias=True)
        return super().default(o)
```

This ensures that regardless of whether the SDK is running on v1 or v2, calling `openapi_dumps` on a dictionary containing Pydantic models will result in valid API-compatible JSON.

**Sources:** [src/openai/_utils/_json.py:28-35](), [src/openai/_utils/_json.py:8-8]()

---

# Page: File Extraction and Processing

# File Extraction and Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Brewfile](Brewfile)
- [examples/httpx2_client.py](examples/httpx2_client.py)
- [scripts/bootstrap](scripts/bootstrap)
- [scripts/format](scripts/format)
- [scripts/lint](scripts/lint)
- [scripts/mock](scripts/mock)
- [scripts/test](scripts/test)
- [src/openai/_files.py](src/openai/_files.py)
- [src/openai/_httpx2.py](src/openai/_httpx2.py)
- [src/openai/_qs.py](src/openai/_qs.py)
- [tests/test_extract_files.py](tests/test_extract_files.py)
- [tests/test_files.py](tests/test_files.py)

</details>



This document describes the file handling system in the OpenAI Python SDK. It covers mechanisms for transmitting files to the API: extracting files from request dictionaries for multipart form data encoding and processing file content for `httpx` compatibility.

## Overview

The SDK handles files primarily for multipart form data requests (e.g., file uploads, audio transcriptions). The system relies on utility functions to locate, extract, and transform various Python file-like objects into formats compatible with the underlying HTTP client.

| Mechanism | Use Case | Implementation | Location |
|-----------|----------|----------------|----------|
| **File Extraction** | Multipart form data requests | `extract_files()` recursively locates and removes file objects from request dictionaries | [src/openai/_utils.py:8-9]() |
| **HTTPX Transformation** | Standardizing file inputs | `to_httpx_files()` and `async_to_httpx_files()` convert inputs to `httpx`-compatible structures | [src/openai/_files.py:51-62](), [src/openai/_files.py:93-104]() |
| **Path Preservation** | Safe mutation | `deepcopy_with_paths()` copies only containers on specific paths to prevent side effects | [src/openai/_files.py:128-145]() |

Sources: [src/openai/_utils.py:8-9](), [src/openai/_files.py:51-62](), [src/openai/_files.py:93-104](), [src/openai/_files.py:128-145]()

## File Type System

The SDK defines a hierarchy of file-related types to support different input formats, including raw bytes, file handles, and filesystem paths.

### File Entity Space Mapping

```mermaid
graph TB
    subgraph "Python_Input_Space"
        PathLike["os.PathLike"]
        IOBase["io.IOBase"]
        Bytes["bytes"]
    end
    
    subgraph "SDK_Type_Entities"
        FileContent["FileContent<br/>(Union[bytes, tuple, IOBase, PathLike])"]
        FileTypes["FileTypes<br/>(Union[FileContent, tuple])"]
        RequestFiles["RequestFiles<br/>(Mapping or Sequence)"]
    end
    
    subgraph "HTTP_Client_Space"
        HttpxFileContent["HttpxFileContent"]
        HttpxFileTypes["HttpxFileTypes"]
        HttpxRequestFiles["HttpxRequestFiles"]
    end
    
    PathLike --> FileContent
    IOBase --> FileContent
    Bytes --> FileContent
    
    FileContent --> FileTypes
    FileTypes --> RequestFiles
    
    RequestFiles -- "to_httpx_files()" --> HttpxRequestFiles
    FileTypes -- "_transform_file()" --> HttpxFileTypes
    FileContent -- "read_file_content()" --> HttpxFileContent
```

Sources: [src/openai/_files.py:25-33](), [src/openai/_files.py:65-76](), [src/openai/_files.py:79-83]()

### Type Hierarchy Table

| Type | Definition | Purpose |
|------|------------|---------|
| `FileContent` | `Union[bytes, tuple, IOBase, PathLike]` | Acceptable raw content sources for files. [src/openai/_files.py:29-32]() |
| `FileTypes` | `Union[FileContent, Tuple[str, FileContent, ...]]` | Flexible file specification allowing for optional filenames and MIME types. [src/openai/_files.py:65-76]() |
| `RequestFiles` | `Union[Mapping[str, FileTypes], Sequence[Tuple[str, FileTypes]]]` | The structure used to pass multiple files in a single request. [src/openai/_files.py:51-62]() |
| `Base64FileInput` | `Union[io.IOBase, os.PathLike]` | Types specifically recognized as sources for file input. [src/openai/_files.py:25-26]() |

Sources: [src/openai/_files.py:25-33](), [src/openai/_files.py:65-76](), [src/openai/_files.py:51-62]()

## File Transformation and Reading

The SDK must convert high-level Python types (like `pathlib.Path`) into raw data that `httpx` can transmit.

### Transformation Logic

The function `_transform_file` handles the conversion logic:
1. If the input is a `PathLike` object, it extracts the filename and reads the bytes immediately. [src/openai/_files.py:67-69]()
2. If the input is a tuple, it recursively processes the content element (index 1) using `read_file_content`. [src/openai/_files.py:73-74]()

### Synchronous vs Asynchronous Processing

The SDK provides parallel implementations for reading file content.

```mermaid
sequenceDiagram
    participant App as "Application Code"
    participant Files as "_files.py"
    participant OS as "File System"
    
    Note over App, OS: Synchronous Path
    App->>Files: to_httpx_files(files)
    Files->>Files: _transform_file(file)
    Files->>OS: path.read_bytes()
    OS-->>Files: binary_data
    Files-->>App: HttpxRequestFiles
    
    Note over App, OS: Asynchronous Path
    App->>Files: await async_to_httpx_files(files)
    Files->>Files: await _async_transform_file(file)
    Files->>OS: await anyio.Path(file).read_bytes()
    OS-->>Files: binary_data
    Files-->>App: HttpxRequestFiles
```

Sources: [src/openai/_files.py:51-83](), [src/openai/_files.py:93-126]()

## Safe Mutation with Path Deepcopy

When extracting files from a request dictionary, the SDK avoids mutating the user's original input objects by using a targeted deepcopy mechanism.

### deepcopy_with_paths Implementation

The `deepcopy_with_paths` utility performs a selective copy. It only creates new instances of dictionaries and lists that exist on the paths where files will be extracted. [src/openai/_files.py:128-145]()

- **Input**: A data structure and a sequence of paths (e.g., `[["documents", "<array>", "file"]]`). [src/openai/_files.py:145]()
- **Logic**:
    - If a dictionary key is on a path, that dictionary is copied. [src/openai/_files.py:161-165]()
    - If a list is encountered and the path contains `"<array>"`, the list and its relevant elements are copied. [src/openai/_files.py:167-172]()
    - All other values (like the actual file bytes or irrelevant metadata) are kept by reference to save memory. [src/openai/_files.py:173]()

Sources: [src/openai/_files.py:128-173]()

## Integration with Multipart Requests

The extraction process prepares the request for `multipart/form-data` encoding.

### Extraction Flow

1. **Path Specification**: The SDK identifies where files are located in the schema using path arrays (e.g., `["file"]` or `["purpose"]`). [tests/test_extract_files.py:17-21]()
2. **Extraction**: `extract_files` traverses the dictionary, pops the file content out, and returns it as a list of tuples formatted for the HTTP client. [tests/test_extract_files.py:11-27]()
3. **Naming**: The field names are generated based on the path. For nested structures, it uses bracket notation (e.g., `foo[bar]`). [tests/test_extract_files.py:21-25]()
4. **Array Formatting**: Supports multiple array formats like `brackets` (`files[]`), `indices` (`files[0]`), or `repeat` (`files`). [src/openai/_qs.py:86-114](), [tests/test_extract_files.py:73-86]()

### Array Format Comparison

| Format | Output Example (Nested) | Output Example (Top Level) |
|--------|-------------------------|----------------------------|
| `brackets` | `items[][file]` | `files[]` |
| `indices` | `items[0][file]` | `files[0]` |
| `repeat` | `items[file]` | `files` |

Sources: [src/openai/_qs.py:86-114](), [tests/test_extract_files.py:73-92]()

---

# Page: Advanced Features

# Advanced Features

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_legacy_response.py](src/openai/_legacy_response.py)
- [src/openai/_response.py](src/openai/_response.py)
- [src/openai/_streaming.py](src/openai/_streaming.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_legacy_response.py](tests/test_legacy_response.py)
- [tests/test_response.py](tests/test_response.py)
- [tests/test_streaming.py](tests/test_streaming.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)

</details>



This page covers advanced capabilities and patterns available in the OpenAI Python SDK for specialized use cases. These features enable sophisticated tool integration, real-time event handling, security validation, and deep customization of the HTTP transport layer.

## Overview of Advanced Capabilities

The OpenAI Python SDK provides several high-level abstractions for complex interaction patterns:

| Feature | Purpose | Key Classes/Methods |
|---------|---------|---------------------|
| **Tool Calling** | Structured function execution and multi-tool integration | `pydantic_function_tool`, `.parse()` |
| **Streaming & Events** | Real-time response processing and event-driven architectures | `Stream`, `AsyncStream`, `AssistantEventHandler` |
| **Webhook Verification** | Securely validate and parse incoming webhook signatures | `client.webhooks.unwrap()`, `verify_signature()` |
| **Custom HTTP Clients** | Configure proxies, custom transports, or alternative event loops | `DefaultHttpxClient`, `http_client` param |
| **Structured Outputs** | Automatic parsing of responses into Pydantic models | `.chat.completions.parse()` |
| **Realtime API** | Low-latency WebSocket-based multi-modal interaction | `RealtimeConnectionManager` |

Detailed documentation for each feature is available in subsections [Tool Calling and Integration](#7.1) through [Custom HTTP Clients and Proxies](#7.4).

Sources: [src/openai/_client.py:137-156](), [src/openai/_streaming.py:23-132](), [src/openai/resources/realtime/realtime.py:99-136]()

## Advanced Streaming Architecture

The SDK handles streaming via Server-Sent Events (SSE). It provides specialized classes to iterate over these streams while maintaining type safety and handling connection lifecycles.

### Streaming Component Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        OPENAI["OpenAI / AsyncOpenAI<br/>src/openai/_client.py"]
        PARSE_CALL[".chat.completions.parse(stream=True)"]
        REALTIME_CALL[".realtime.connect()"]
    end
    
    subgraph "Stream Objects"
        STREAM["Stream[T]<br/>src/openai/_streaming.py"]
        ASYNC_STREAM["AsyncStream[T]<br/>src/openai/_streaming.py"]
        DECODER["SSEBytesDecoder<br/>src/openai/_streaming.py"]
        RT_MGR["RealtimeConnectionManager<br/>src/openai/resources/realtime/realtime.py"]
    end
    
    subgraph "Response Processing"
        API_RESP["APIResponse / AsyncAPIResponse<br/>src/openai/_response.py"]
        ITER["__iter__() / __aiter__()"]
        PROC["_process_response_data()"]
    end
    
    OPENAI --> PARSE_CALL
    OPENAI --> REALTIME_CALL
    
    PARSE_CALL --> API_RESP
    REALTIME_CALL --> RT_MGR
    
    API_RESP --> STREAM
    API_RESP --> ASYNC_STREAM
    
    STREAM --> DECODER
    ASYNC_STREAM --> DECODER
    
    STREAM --> ITER
    ITER --> PROC
```

**Streaming Flow**: When a streaming request is made, the client returns a `Stream` or `AsyncStream` instance [src/openai/_streaming.py:23-132](). These classes wrap an `SSEBytesDecoder` that parses raw bytes from the `httpx.Response` into `ServerSentEvent` objects [src/openai/_streaming.py:52-53](). For low-latency multi-modal use cases, the `Realtime` resource provides a `connect()` method returning a `RealtimeConnectionManager` for stateful WebSocket communication [src/openai/resources/realtime/realtime.py:99-136]().

For details, see [Streaming and Event Handling](#7.2).

Sources: [src/openai/_streaming.py:23-160](), [src/openai/_response.py:142-183](), [src/openai/resources/realtime/realtime.py:99-182]()

## Structured Outputs and Parsing

The SDK includes a `.parse()` helper that integrates with Pydantic to provide "Structured Outputs." This feature automatically converts Pydantic models into JSON schemas for the API and deserializes the results back into typed Python objects.

### Structured Output Flow

```mermaid
graph LR
    subgraph "Request Phase"
        PYD_MODEL["Pydantic Model<br/>(User Defined)"]
        PARSE_METHOD["chat.completions.parse()"]
        PYD_TOOL["pydantic_function_tool()"]
    end
    
    subgraph "Internal Transformation"
        TRANSFORM["_process_response_data()"]
        CONSTRUCT["construct_type()"]
    end
    
    subgraph "Response Phase"
        RAW_JSON["Raw JSON Response"]
        PARSED_OBJ["ParsedChatCompletion<br/>(Typed Instance)"]
    end
    
    PYD_MODEL --> PARSE_METHOD
    PYD_TOOL --> PARSE_METHOD
    PARSE_METHOD --> RAW_JSON
    RAW_JSON --> TRANSFORM
    TRANSFORM --> CONSTRUCT
    CONSTRUCT --> PARSED_OBJ
```

**Key Behaviors**:
- **Automatic Schema Generation**: Pydantic models passed to the SDK are processed via `construct_type` to ensure correct serialization and validation [src/openai/_base_client.py:76-77]().
- **Validation**: If the API responds with invalid data for the expected schema, an `APIResponseValidationError` is raised if `_strict_response_validation` is enabled [src/openai/_client.py:154-156]().
- **Tool Integration**: Using `pydantic_function_tool` (exported in `openai.__init__`) allows function arguments to be automatically validated against Pydantic models [src/openai/__init__.py:104]().

For details, see [Tool Calling and Integration](#7.1).

Sources: [src/openai/_response.py:129-183](), [src/openai/_client.py:154-156](), [src/openai/__init__.py:104]()

## Response Wrapper Patterns

The SDK provides `with_raw_response` and `with_streaming_response` methods on every resource to allow access to underlying HTTP metadata.

- **`with_raw_response`**: Returns an `APIResponse` object containing the parsed data as well as `headers` (e.g., `x-request-id`) and the `status_code` [src/openai/_response.py:49-93]().
- **`with_streaming_response`**: Returns a context manager that yields an `APIResponse`, allowing manual control over when the response body is read via `.read()`, `.text()`, or `.json()` [src/openai/_response.py:114-121]().

Sources: [src/openai/_response.py:49-127](), [src/openai/_legacy_response.py:46-146]()

## Webhook Verification

The SDK includes utilities to verify the authenticity of webhooks sent by OpenAI. This prevents unauthorized requests by validating the signature using a shared `webhook_secret`.

**Security Flow**: The `webhook_secret` is typically configured during client initialization [src/openai/_client.py:134](). The `Webhooks` resource (available via `client.webhooks`) provides methods to validate signatures. If validation fails, it raises an `InvalidWebhookSignatureError` [src/openai/__init__.py:36]().

For details, see [Webhook Verification](#7.3).

Sources: [src/openai/_client.py:134](), [src/openai/__init__.py:36-74]()

## Custom HTTP Clients and Proxies

For advanced networking environments, the SDK allows users to provide their own `httpx` client. This is useful for:
- **Proxies**: Configuring corporate proxies via `httpx.Proxy`.
- **Custom Timeouts**: Setting specific connection, read, or write timeouts [src/openai/_base_client.py:84-91]().
- **Alternative Backends**: Using `aiohttp` for improved concurrency performance in the async client [src/openai/_base_client.py:40]().

**Customization**: Pass a `httpx.Client` (or `httpx.AsyncClient`) to the `http_client` parameter of the `OpenAI` constructor [src/openai/_client.py:145]().

For details, see [Custom HTTP Clients and Proxies](#7.4).

Sources: [src/openai/_client.py:145](), [src/openai/_base_client.py:40](), [src/openai/_types.py:19-20]()

---

# Page: Tool Calling and Integration

# Tool Calling and Integration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/images.py](src/openai/resources/images.py)
- [src/openai/types/beta/assistant_response_format_option.py](src/openai/types/beta/assistant_response_format_option.py)
- [src/openai/types/beta/assistant_response_format_option_param.py](src/openai/types/beta/assistant_response_format_option_param.py)
- [src/openai/types/beta/function_tool_param.py](src/openai/types/beta/function_tool_param.py)
- [src/openai/types/chat/__init__.py](src/openai/types/chat/__init__.py)
- [src/openai/types/chat/chat_completion_assistant_message_param.py](src/openai/types/chat/chat_completion_assistant_message_param.py)
- [src/openai/types/chat/chat_completion_message.py](src/openai/types/chat/chat_completion_message.py)
- [src/openai/types/chat/chat_completion_message_tool_call.py](src/openai/types/chat/chat_completion_message_tool_call.py)
- [src/openai/types/chat/chat_completion_message_tool_call_param.py](src/openai/types/chat/chat_completion_message_tool_call_param.py)
- [src/openai/types/chat/chat_completion_message_tool_call_union_param.py](src/openai/types/chat/chat_completion_message_tool_call_union_param.py)
- [src/openai/types/chat/chat_completion_tool_param.py](src/openai/types/chat/chat_completion_tool_param.py)
- [src/openai/types/image_edit_params.py](src/openai/types/image_edit_params.py)
- [src/openai/types/image_generate_params.py](src/openai/types/image_generate_params.py)
- [src/openai/types/responses/tool.py](src/openai/types/responses/tool.py)
- [src/openai/types/responses/tool_param.py](src/openai/types/responses/tool_param.py)
- [src/openai/types/shared/function_definition.py](src/openai/types/shared/function_definition.py)
- [src/openai/types/shared_params/function_definition.py](src/openai/types/shared_params/function_definition.py)
- [tests/api_resources/test_images.py](tests/api_resources/test_images.py)
- [tests/compat/test_tool_param.py](tests/compat/test_tool_param.py)

</details>



This document covers tool calling and integration mechanisms in the OpenAI Python library. It explains how to define tools (functions that the model can call), configure tool selection strategies, handle tool outputs, and leverage automatic parsing of tool call arguments using Pydantic.

---

## Purpose and Scope

Tool calling enables language models to invoke external functions and built-in capabilities. This document covers:

- **Tool types**: Function tools (custom code) and built-in tools like MCP, Web Search, and Code Interpreter.
- **Tool definition patterns**: Manual schema creation and specialized parameters for different tool categories.
- **Tool choice strategies**: Controlling which tools the model can or must use.
- **Tool output handling**: Handling tool call responses and continuing the conversation.
- **Automatic parsing**: Using the `parse()` method to convert tool call arguments into typed Python objects.

---

## Tool Types and Categories

The library supports a wide array of tools, ranging from standard `function` tools to advanced Model Context Protocol (MCP) and multi-modal tools.

### Tool Type Overview

```mermaid
graph TB
    subgraph "Tool Categories"
        FUNC["Function Tools<br/>(Custom Code)"]
        MCP_TOOL["MCP Tools<br/>(Remote Servers)"]
        WEB_TOOL["Web Search Tools"]
        COMP_TOOL["Computer Use Tools"]
        IMG_TOOL["Image Generation Tools"]
    end
    
    subgraph "Code Entities"
        T_PARAM["ToolParam (Union)"]
        C_FUNC["ChatCompletionFunctionToolParam"]
        C_MCP["Mcp (TypedDict)"]
        C_WEB["WebSearchToolParam"]
        C_IMG["ImageGeneration (TypedDict)"]
    end
    
    FUNC --> C_FUNC
    MCP_TOOL --> C_MCP
    WEB_TOOL --> C_WEB
    IMG_TOOL --> C_IMG
    
    C_FUNC --> T_PARAM
    C_MCP --> T_PARAM
    C_WEB --> T_PARAM
    C_IMG --> T_PARAM
    
    style FUNC fill:#ffffff
    style MCP_TOOL fill:#ffffff
    style IMG_TOOL fill:#ffffff
```

**Sources:** [src/openai/types/responses/tool_param.py:26-42](), [src/openai/types/chat/__init__.py:24-31]()

### Function Tools

Function tools are user-defined functions with schemas. The model generates JSON arguments matching the schema.

**Core type definitions:**
- `ChatCompletionToolParam`: A `TypeAlias` for `ChatCompletionFunctionToolParam` [src/openai/types/chat/chat_completion_tool_param.py:14]().
- `ChatCompletionMessageToolCall`: Represents a tool call generated by the model [src/openai/types/chat/chat_completion_message_tool_call.py:17]().
- `FunctionDefinition`: The inner schema containing name, description, and parameters [src/openai/types/shared_params/function_definition.py:13-46]().

**Sources:** [src/openai/types/chat/chat_completion_tool_param.py:1-15](), [src/openai/types/chat/chat_completion_message_tool_call.py:1-18](), [src/openai/types/shared_params/function_definition.py:1-46]()

### Model Context Protocol (MCP) Tools

MCP tools allow the model to access remote servers. These tools require a `server_label`, `server_url` (or `connector_id`/`tunnel_id`), and authorization tokens [src/openai/types/responses/tool_param.py:115-194](). The SDK provides filters for allowed tools via `McpAllowedToolsMcpToolFilter` [src/openai/types/responses/tool_param.py:49-63]() and approval requirements via `McpRequireApproval` [src/openai/types/responses/tool_param.py:112]().

**Sources:** [src/openai/types/responses/tool_param.py:115-194](), [src/openai/types/responses/tool.py:113-194](), [src/openai/types/responses/tool_param.py:49-112]()

---

## Defining Function Tools

Tools can be defined as dictionaries or generated from Pydantic models.

### Manual Tool Definition

Manual definitions use the `ChatCompletionToolParam` structure:

```python
# Example of manual instantiation
from openai.types.chat import ChatCompletionToolParam

tool = ChatCompletionToolParam(
    type="function",
    function={
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {"location": {"type": "string"}}}
    }
)
```

**Sources:** [tests/compat/test_tool_param.py:4-8](), [src/openai/types/chat/chat_completion_tool_param.py:14]()

### Strict Mode and JSON Schema

When using `strict: True` in a `FunctionDefinition`, the model will follow the exact schema defined. This is a requirement for Structured Outputs [src/openai/types/shared_params/function_definition.py:38-44]().

**Sources:** [src/openai/types/shared_params/function_definition.py:38-46]()

---

## Tool Choice Strategies

The `tool_choice` parameter controls model behavior regarding tools.

| Strategy | Type | Behavior |
|----------|------|----------|
| **Auto** | `Literal["auto"]` | Model decides whether to call a tool [src/openai/types/chat/chat_completion_tool_choice_option_param.py](). |
| **Required**| `Literal["required"]`| Model must call at least one tool. |
| **None** | `Literal["none"]` | Model will not call any tools. |
| **Named** | `ChatCompletionNamedToolChoiceParam` | Forces the model to call a specific tool by name [src/openai/types/chat/chat_completion_named_tool_choice_param.py:11](). |

**Sources:** [src/openai/types/chat/chat_completion_tool_choice_option_param.py:1-15](), [src/openai/types/chat/chat_completion_named_tool_choice_param.py:1-15]()

---

## Automatic Parsing with parse()

The `client.chat.completions.parse()` method provides automatic deserialization of tool call arguments into Pydantic models.

### Parsing Flow

```mermaid
graph LR
    subgraph "Natural Language Space"
        USER_PROMPT["User: 'Search for orders'"]
    end
    
    subgraph "Code Entity Space"
        PARSE_METHOD["chat.completions.parse()"]
        PYD_MODEL["Pydantic BaseModel"]
        TOOL_CALL["ChatCompletionMessageToolCall"]
        PARSED_ARGS["tool_call.function.parsed_arguments"]
    end
    
    USER_PROMPT --> PARSE_METHOD
    PYD_MODEL --> PARSE_METHOD
    PARSE_METHOD --> TOOL_CALL
    TOOL_CALL --> PARSED_ARGS
    PARSED_ARGS -- "Instance of" --> PYD_MODEL
    
    style PARSE_METHOD fill:#ffffff
    style PYD_MODEL fill:#ffffff
```

**Sources:** [src/openai/types/chat/parsed_chat_completion.py:10-14](), [src/openai/types/chat/parsed_function_tool_call.py:20-23]()

---

## Handling Tool Call Responses

To provide tool results back to the model, the user must create a message with the `tool` role, referencing the `tool_call_id`.

### Message Sequence for Tool Execution

```mermaid
sequenceDiagram
    participant App as "Application Code"
    participant SDK as "OpenAI Python SDK"
    participant API as "OpenAI API"

    App->>SDK: chat.completions.create(messages, tools)
    SDK->>API: POST /chat/completions
    API-->>SDK: ChatCompletion (tool_calls=[ID_1])
    SDK-->>App: ChatCompletionMessage (assistant)
    
    Note over App: App executes local function
    
    App->>SDK: chat.completions.create(messages + assistant_msg + tool_msg)
    Note right of App: tool_msg has tool_call_id=ID_1
    SDK->>API: POST /chat/completions
    API-->>SDK: ChatCompletion (final text)
    SDK-->>App: ChatCompletionMessage
```

**Sources:** [src/openai/types/chat/chat_completion_assistant_message_param.py:81-83](), [src/openai/types/chat/chat_completion_tool_message_param.py:16-24]()

### Data Structures for Responses

- **Assistant Message**: Contains `tool_calls` which is an iterable of `ChatCompletionMessageToolCallUnionParam` [src/openai/types/chat/chat_completion_assistant_message_param.py:81-83]().
- **Tool Message**: A `ChatCompletionToolMessageParam` containing the `content` (result) and the `tool_call_id` [src/openai/types/chat/chat_completion_tool_message_param.py:16-24]().
- **Legacy Function Call**: The `function_call` field in `ChatCompletionMessage` is deprecated and replaced by `tool_calls` [src/openai/types/chat/chat_completion_message.py:82-90]().

**Sources:** [src/openai/types/chat/chat_completion_assistant_message_param.py:46-83](), [src/openai/types/chat/chat_completion_tool_message_param.py:1-25](), [src/openai/types/chat/chat_completion_message.py:82-90]()

---

## Specialized Tool Integration: Images

The SDK provides specialized methods for image-related tools through the `Images` resource [src/openai/resources/images.py:28](). These methods support both standard and streaming tool-like behaviors.

- **Image Variations**: `create_variation` generates new images based on an input [src/openai/resources/images.py:50-126]().
- **Image Editing**: `edit` allows for prompt-based modifications and supports streaming events via `ImageEditStreamEvent` [src/openai/resources/images.py:129-154](), [src/openai/types/image_edit_stream_event.py]().
- **Parameters**: Defined in `ImageEditParams` [src/openai/types/image_edit_params.py:160]() and `ImageGenerateParams` [src/openai/types/image_generate_params.py:159]().

**Sources:** [src/openai/resources/images.py:28-154](), [src/openai/types/image_edit_params.py:1-161](), [src/openai/types/image_generate_params.py:1-160]()

---

# Page: Streaming and Event Handling

# Streaming and Event Handling

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/image_stream.py](examples/image_stream.py)
- [src/openai/_legacy_response.py](src/openai/_legacy_response.py)
- [src/openai/_response.py](src/openai/_response.py)
- [src/openai/_streaming.py](src/openai/_streaming.py)
- [src/openai/lib/streaming/_assistants.py](src/openai/lib/streaming/_assistants.py)
- [src/openai/lib/streaming/responses/_events.py](src/openai/lib/streaming/responses/_events.py)
- [src/openai/types/image_edit_partial_image_event.py](src/openai/types/image_edit_partial_image_event.py)
- [src/openai/types/image_edit_stream_event.py](src/openai/types/image_edit_stream_event.py)
- [tests/test_legacy_response.py](tests/test_legacy_response.py)
- [tests/test_response.py](tests/test_response.py)
- [tests/test_streaming.py](tests/test_streaming.py)

</details>



## Purpose and Scope

This document explains the streaming architecture in the OpenAI Python SDK, which enables real-time processing of model responses as they are generated. Streaming is supported across multiple API endpoints including Chat Completions, Responses, Assistants, and Image Generation APIs. The SDK provides both synchronous and asynchronous streaming interfaces with event-driven patterns for processing incremental data.

For information about parsed responses and structured outputs without streaming, see [Parsed Responses and Structured Outputs](#4.1.3). For tool calling patterns, see [7.1 Tool Calling and Integration]().

## Architecture Overview

The streaming system is built on three foundational layers: HTTP transport via Server-Sent Events (SSE), generic stream wrappers, and API-specific event managers.

**Streaming System Layers**

```mermaid
graph TB
    subgraph "HTTP_Layer"
        SSE["SSEBytesDecoder / SSEDecoder<br/>SSE Decoding Logic"]
        HTTPX["httpx.Response Stream"]
    end
    
    subgraph "Stream_Wrappers"
        Stream["Stream[T]<br/>src/openai/_streaming.py"]
        AsyncStream["AsyncStream[T]<br/>src/openai/_streaming.py"]
    end
    
    subgraph "Event_Managers"
        ChatStreamMgr["ChatCompletionStreamManager<br/>Context Manager"]
        ResponseStreamMgr["ResponseStreamManager<br/>Context Manager"]
        AssistantHandler["AssistantEventHandler<br/>Callback Pattern"]
    end
    
    subgraph "Event_Types"
        ChatEvents["ChatCompletionChunk<br/>ChatCompletionStreamEvent"]
        ResponseEvents["ResponseStreamEvent<br/>response.output_text.delta<br/>response.done"]
        AssistantEvents["AssistantStreamEvent<br/>thread.message.delta<br/>thread.run.step.delta"]
        ImageEvents["ImageEditStreamEvent<br/>image_edit.partial_image"]
    end
    
    HTTPX --> SSE
    SSE --> Stream
    SSE --> AsyncStream
    
    Stream --> ChatStreamMgr
    Stream --> ResponseStreamMgr
    Stream --> AssistantHandler
    
    AsyncStream --> ChatStreamMgr
    AsyncStream --> ResponseStreamMgr
    AsyncStream --> AssistantHandler
    
    ChatStreamMgr --> ChatEvents
    ResponseStreamMgr --> ResponseEvents
    AssistantHandler --> AssistantEvents
```

Sources: [src/openai/_streaming.py:23-42](), [src/openai/lib/streaming/chat/_completions.py:122-143](), [src/openai/lib/streaming/chat/_completions.py:46-65](), [src/openai/types/image_edit_stream_event.py:12-14]()

## Core Streaming Classes

### Stream and AsyncStream

The `Stream[T]` and `AsyncStream[T]` classes provide generic wrappers over HTTP SSE connections. They implement iterator protocols and handle connection lifecycle management.

**Key characteristics:**
- `Stream[T]` implements `Iterator[T]` for synchronous iteration [src/openai/_streaming.py:48-50]().
- `AsyncStream[T]` implements `AsyncIterator[T]` for asynchronous iteration [src/openai/_streaming.py:157-159]().
- Both provide `close()` methods for connection cleanup [src/openai/_streaming.py:123-129](), [src/openai/_streaming.py:235-241]().
- Events are yielded as they arrive from the API, filtered for `[DONE]` sentinels [src/openai/_streaming.py:62-64]().
- Type parameter `_T` specifies the event type (e.g., `ChatCompletionChunk`) [src/openai/_streaming.py:20-23]().

**Data Flow in Stream Classes**

```mermaid
sequenceDiagram
    participant C as Client (OpenAI/AsyncOpenAI)
    participant S as Stream / AsyncStream
    participant D as SSEBytesDecoder
    participant R as httpx.Response
    
    C->>S: __init__(cast_to, response, client)
    S->>C: _make_sse_decoder()
    C-->>S: SSEBytesDecoder instance
    loop Iteration
        S->>R: iter_bytes() / aiter_bytes()
        R-->>S: Raw bytes
        S->>D: iter_bytes(bytes) / aiter_bytes(bytes)
        D-->>S: ServerSentEvent
        S->>S: sse.json()
        S->>C: _process_response_data(data, cast_to)
        C-->>S: Parsed Object (T)
        S-->>User: Yield T
    end
    S->>R: close()
```

Sources: [src/openai/_streaming.py:30-43](), [src/openai/_streaming.py:55-107](), [src/openai/_streaming.py:165-219]()

## Chat Completions Streaming

### Event Types and Stream Manager

Chat Completions streaming uses `ChatCompletionStreamManager` which provides high-level event processing and state accumulation. The manager wraps the raw `Stream[ChatCompletionChunk]` and emits structured events defined in `ChatCompletionStreamEvent`.

**Chat Completion Stream Events**

```mermaid
graph TB
    chunk["chunk<br/>Raw ChatCompletionChunk"]
    
    content_delta["content.delta<br/>Incremental text/data"]
    content_done["content.done<br/>Complete content + parsed"]
    
    refusal_delta["refusal.delta<br/>Incremental refusal text"]
    refusal_done["refusal.done<br/>Complete refusal"]
    
    tool_delta["tool_calls.delta<br/>Tool call fragments"]
    tool_args_delta["tool_calls.function.arguments.delta<br/>Incremental JSON"]
    tool_args_done["tool_calls.function.arguments.done<br/>Parsed arguments"]
    
    chunk --> content_delta
    chunk --> refusal_delta
    chunk --> tool_delta
    
    content_delta --> content_done
    refusal_delta --> refusal_done
    tool_delta --> tool_args_delta
    tool_args_delta --> tool_args_done
```

Sources: [src/openai/lib/streaming/chat/_completions.py:11-24](), [src/openai/lib/streaming/chat/_completions.py:113-120]()

### State Accumulation

The stream manager maintains a `ChatCompletionStreamState` that accumulates deltas into a complete `ParsedChatCompletion` object. This allows accessing the current state at any point during streaming via the `current_completion_snapshot` property [src/openai/lib/streaming/chat/_completions.py:65-66](), [src/openai/lib/streaming/chat/_completions.py:110-111]().

### Parsed Streaming with Structured Outputs

When using `response_format` with a Pydantic model, the stream manager incrementally parses JSON and emits the fully parsed object in `content.done` events [src/openai/lib/streaming/chat/_completions.py:93-102](). The `to_strict_json_schema` utility ensures that the Pydantic model is converted into a schema the API can handle for structured output [src/openai/lib/_pydantic.py:16-24]().

Sources: [src/openai/lib/streaming/chat/_completions.py:113-120](), [src/openai/lib/_parsing/_completions.py:190-195](), [src/openai/lib/_pydantic.py:16-24]()

## Responses API Streaming

The Responses API uses `ResponseStreamEvent` types which include wrappers with snapshots added on. Events are namespaced under the response object structure.

**Response Stream Event Types:**
- `ResponseTextDeltaEvent`: Includes incremental text and a cumulative `snapshot` string [src/openai/lib/streaming/responses/_events.py:72-74]().
- `ResponseTextDoneEvent`: Includes the final `parsed` object [src/openai/lib/streaming/responses/_events.py:76-77]().
- `ResponseFunctionCallArgumentsDeltaEvent`: Includes incremental arguments and a `snapshot` [src/openai/lib/streaming/responses/_events.py:80-82]().
- `ResponseCompletedEvent`: Contains the final `ParsedResponse` [src/openai/lib/streaming/responses/_events.py:84-85]().

Sources: [src/openai/lib/streaming/responses/_events.py:88-148]()

## Assistants API Streaming

### AssistantEventHandler Pattern

The Assistants API uses a callback-based event handler pattern. `AssistantEventHandler` and `AsyncAssistantEventHandler` define lifecycle methods that are called as events arrive.

**AssistantEventHandler Architecture**

```mermaid
graph TB
    subgraph "Event_Handler_Lifecycle"
        iterate["__iter__() / __aiter__()<br/>Process SSE events"]
        emit["_emit_sse_event(event)<br/>Dispatch to callbacks"]
    end
    
    subgraph "Callback_Methods"
        on_event["on_event(event)<br/>Every SSE event"]
        on_message_delta["on_message_delta(delta, snapshot)"]
        on_text_delta["on_text_delta(delta, snapshot)"]
        on_tool_call_delta["on_tool_call_delta(delta, snapshot)"]
    end
    
    iterate --> emit
    emit --> on_event
    emit --> on_message_delta
    emit --> on_text_delta
    emit --> on_tool_call_delta
```

Sources: [src/openai/lib/streaming/_assistants.py:31-60](), [src/openai/lib/streaming/_assistants.py:146-203](), [src/openai/_streaming.py:66-84]() (Assistants events special casing).

## Image Generation Streaming

The Image API supports streaming partial image data during generation. This is controlled by the `stream=True` and `partial_images` parameters in the `images.generate` call [examples/image_stream.py:13-20]().

**Image Stream Events:**
- `ImageEditPartialImageEvent`: Emitted when a partial image is available. Contains `b64_json` and a `partial_image_index` [src/openai/types/image_edit_partial_image_event.py:10-35]().
- `ImageEditCompletedEvent`: Emitted when the final image is generated.

Sources: [src/openai/types/image_edit_stream_event.py:12-14](), [examples/image_stream.py:22-46]()

## Stream Managers and Context Managers

Stream managers ensure the response cannot be leaked if you don't read the stream to completion by providing context manager support.

**Stream Manager Lifecycle**

```mermaid
graph LR
    enter["__enter__()<br/>Create raw stream<br/>Initialize manager"]
    use["User iterates events"]
    exit["__exit__()<br/>Close raw stream"]
    
    enter --> use
    use --> exit
```

Sources: [src/openai/lib/streaming/chat/_completions.py:148-157](), [src/openai/lib/streaming/chat/_completions.py:159-167](), [src/openai/_streaming.py:112-121]()

## Event Accumulation Internals

### The accumulate_delta Utility

The `accumulate_delta` function is the core logic for merging delta objects into snapshot objects [src/openai/lib/streaming/chat/_completions.py:25](). This is used by stream states to maintain the "current completion" view.

For structured outputs and tool calls, the SDK accumulates JSON string fragments. The `construct_type` function handles:
1. **Partial dictionaries**: Interim delta events contain incomplete JSON represented as dictionaries.
2. **Type coercion**: Converts raw values to expected types.
3. **Nested model construction**: Recursively builds nested Pydantic models.

Sources: [src/openai/lib/streaming/chat/_completions.py:25-29](), [src/openai/lib/_parsing/_completions.py:113-125](), [src/openai/lib/_parsing/_completions.py:140-154]()

## Summary Table of Streaming Classes

| Class | Purpose | Primary Interface |
| :--- | :--- | :--- |
| `Stream[_T]` | Low-level sync SSE wrapper | `Iterator[_T]` |
| `AsyncStream[_T]` | Low-level async SSE wrapper | `AsyncIterator[_T]` |
| `ChatCompletionStream` | High-level Chat manager | `__iter__` yielding `ChatCompletionStreamEvent` |
| `AssistantEventHandler` | Assistant callback manager | `on_text_delta`, `on_tool_call_delta`, etc. |
| `ResponseStreamEvent` | Responses API events | Discriminator-based Union with snapshots |

Sources: [src/openai/_streaming.py:23-132](), [src/openai/lib/streaming/chat/_completions.py:46-120](), [src/openai/lib/streaming/responses/_events.py:88-148](), [src/openai/lib/streaming/_assistants.py:31-60]()

---

# Page: Webhook Verification

# Webhook Verification

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/openai/resources/conversations/api.md](src/openai/resources/conversations/api.md)
- [src/openai/resources/realtime/api.md](src/openai/resources/realtime/api.md)
- [src/openai/resources/webhooks/__init__.py](src/openai/resources/webhooks/__init__.py)
- [src/openai/resources/webhooks/webhooks.py](src/openai/resources/webhooks/webhooks.py)
- [tests/api_resources/webhooks/__init__.py](tests/api_resources/webhooks/__init__.py)

</details>



## Purpose and Scope

This document explains how to verify webhook signatures sent by the OpenAI API to ensure that webhook requests to your application originate from OpenAI and have not been tampered with. Webhook verification is a critical security measure for production deployments.

The SDK provides specialized resource classes, `Webhooks` and `AsyncWebhooks`, to handle the extraction of signatures, validation of timestamps (replay protection), and HMAC verification against a shared secret.

---

## Overview

The OpenAI API sends webhooks to notify your application about asynchronous events such as batch completions, fine-tuning job updates, or realtime call events. To ensure these requests are authentic, OpenAI signs each webhook payload.

The verification process involves:
1.  **Timestamp Validation**: Checking the `webhook-timestamp` header against the current time to prevent replay attacks [src/openai/resources/webhooks/webhooks.py:73-86]().
2.  **Signature Comparison**: Computing an HMAC-SHA256 hash of the payload and comparing it with the values in the `webhook-signature` header [src/openai/resources/webhooks/webhooks.py:105-115]().

### Webhook Verification Data Flow

This diagram illustrates the internal logic of the `unwrap` method and its interaction with the underlying verification utility.

```mermaid
sequenceDiagram
    participant App as "Your Server"
    participant WH as "Webhooks.unwrap()"
    participant VS as "Webhooks.verify_signature()"
    participant HMAC as "hmac module"

    App->>WH: "unwrap(payload, headers, secret)"
    WH->>VS: "verify_signature(payload, headers, secret)"
    
    VS->>VS: "get_required_header('webhook-signature')"
    VS->>VS: "get_required_header('webhook-timestamp')"
    VS->>VS: "Check tolerance (default 300s)"
    
    VS->>VS: "Prepare signed_payload: {id}.{timestamp}.{body}"
    VS->>HMAC: "new(decoded_secret, signed_payload, sha256)"
    HMAC-->>VS: "expected_signature"
    
    VS->>VS: "hmac.compare_digest()"
    
    alt "Signature Valid"
        VS-->>WH: "Return None"
        WH->>WH: "json.loads(payload)"
        WH->>WH: "construct_type(UnwrapWebhookEvent)"
        WH-->>App: "UnwrapWebhookEvent object"
    else "Signature Invalid"
        VS-->>App: "raise InvalidWebhookSignatureError"
    end
```
Sources: [src/openai/resources/webhooks/webhooks.py:23-42](), [src/openai/resources/webhooks/webhooks.py:44-117](), [src/openai/resources/webhooks/webhooks.py:118-139](), [src/openai/resources/webhooks/webhooks.py:141-213]()

---

## Configuration

### Webhook Secret
The secret key is used as the HMAC key. It can be provided in three ways:
1.  **Environment Variable**: Setting `OPENAI_WEBHOOK_SECRET`.
2.  **Client Initialization**: Passing `webhook_secret` to the `OpenAI` or `AsyncOpenAI` constructor [src/openai/resources/webhooks/webhooks.py:60-67]().
3.  **Method Argument**: Passing `secret` directly to `unwrap()` or `verify_signature()` [src/openai/resources/webhooks/webhooks.py:28-32]().

If the secret starts with the prefix `whsec_`, the SDK automatically strips the prefix and base64-decodes the remainder before use [src/openai/resources/webhooks/webhooks.py:98-99](). Otherwise, it is encoded as UTF-8 [src/openai/resources/webhooks/webhooks.py:101]().

Sources: [src/openai/resources/webhooks/webhooks.py:60-67](), [src/openai/resources/webhooks/webhooks.py:98-102]()

---

## Verification Implementation

The SDK provides two primary methods within the `Webhooks` (sync) and `AsyncWebhooks` (async) classes [src/openai/resources/webhooks/__init__.py:6-11]().

### 1. `unwrap()`
This is the high-level convenience method. It verifies the signature and then parses the raw payload into a typed `UnwrapWebhookEvent` object [src/openai/resources/webhooks/webhooks.py:23-42]().

*   **Implementation**: It calls `verify_signature` internally [src/openai/resources/webhooks/webhooks.py:34]().
*   **Parsing**: It uses the `construct_type` utility to transform the JSON payload into a model [src/openai/resources/webhooks/webhooks.py:38-41]().

### 2. `verify_signature()`
This method performs the cryptographic validation without parsing the body.

*   **Headers Required**: It expects `webhook-id`, `webhook-timestamp`, and `webhook-signature` [src/openai/resources/webhooks/webhooks.py:69-71]().
*   **Replay Protection**: It enforces a default `tolerance` of 300 seconds (5 minutes). If the `webhook-timestamp` is older or newer than this window relative to the server time, it raises `InvalidWebhookSignatureError` [src/openai/resources/webhooks/webhooks.py:81-85]().
*   **Multi-Signature Support**: The `webhook-signature` header can contain multiple signatures separated by spaces. The SDK splits these and accepts the payload if *any* signature matches [src/openai/resources/webhooks/webhooks.py:90-95]().

### Entity Mapping: Natural Language to Code

| Concept | Code Entity | File Location |
| :--- | :--- | :--- |
| **Webhook Resource** | `Webhooks` / `AsyncWebhooks` | [src/openai/resources/webhooks/webhooks.py:22]() |
| **Verification Logic** | `verify_signature` | [src/openai/resources/webhooks/webhooks.py:44]() |
| **Parsing & Verification** | `unwrap` | [src/openai/resources/webhooks/webhooks.py:23]() |
| **Event Model** | `UnwrapWebhookEvent` | [src/openai/types/webhooks/unwrap_webhook_event.py]() |
| **Error Type** | `InvalidWebhookSignatureError` | [src/openai/resources/webhooks/webhooks.py:16]() |

```mermaid
graph LR
    subgraph "SDK_Core"
        Client["OpenAI Client"]
    end

    subgraph "Webhook_Resource"
        WH["Webhooks Class"]
        WH_A["AsyncWebhooks Class"]
    end

    subgraph "Logic_Entities"
        Verify["verify_signature()"]
        Unwrap["unwrap()"]
    end

    subgraph "Data_Models"
        Event["UnwrapWebhookEvent"]
    end

    Client --> WH
    Client --> WH_A
    WH --> Unwrap
    WH --> Verify
    Unwrap -- "calls" --> Verify
    Unwrap -- "returns" --> Event
```
Sources: [src/openai/resources/webhooks/webhooks.py:22-118](), [src/openai/resources/webhooks/__init__.py:6-11](), [src/openai/resources/webhooks/webhooks.py:15-17]()

---

## Event Types

The `UnwrapWebhookEvent` can represent various events occurring within the OpenAI platform. These events are handled via the `construct_type` utility during the `unwrap` process [src/openai/resources/webhooks/webhooks.py:38-41]().

While the specific event types are defined in the types directory, the `Webhooks` resource is designed to handle any event conforming to the `UnwrapWebhookEvent` structure [src/openai/resources/webhooks/webhooks.py:17](). This includes events for:
*   **Batch Operations**: Notifications for batch success or failure.
*   **Fine-Tuning**: Updates on training progress and job completion.
*   **Realtime**: Incoming call events or session updates.
*   **Conversations**: Management of persistent state and items [src/openai/resources/conversations/api.md:6-19]().

Sources: [src/openai/resources/webhooks/webhooks.py:17](), [src/openai/resources/conversations/api.md:6-19]()

---

## Error Handling

When verification fails, the SDK raises `InvalidWebhookSignatureError` [src/openai/resources/webhooks/webhooks.py:16]().

Common reasons for failure:
*   **Timestamp Drift**: The server's clock is out of sync with OpenAI's clock beyond the 300s tolerance [src/openai/resources/webhooks/webhooks.py:81-85]().
*   **Incorrect Secret**: The `webhook_secret` provided does not match the one configured. If no secret is provided and none is found on the client, a `ValueError` is raised [src/openai/resources/webhooks/webhooks.py:63-67]().
*   **Payload Modification**: If the request body was modified before reaching the verification logic, the HMAC check will fail [src/openai/resources/webhooks/webhooks.py:112-115]().

Sources: [src/openai/resources/webhooks/webhooks.py:16](), [src/openai/resources/webhooks/webhooks.py:63-67](), [src/openai/resources/webhooks/webhooks.py:81-85](), [src/openai/resources/webhooks/webhooks.py:112-115]()

---

# Page: Custom HTTP Clients and Proxies

# Custom HTTP Clients and Proxies

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Brewfile](Brewfile)
- [README.md](README.md)
- [examples/httpx2_client.py](examples/httpx2_client.py)
- [requirements-dev.lock](requirements-dev.lock)
- [requirements.lock](requirements.lock)
- [scripts/bootstrap](scripts/bootstrap)
- [scripts/format](scripts/format)
- [scripts/lint](scripts/lint)
- [scripts/mock](scripts/mock)
- [scripts/test](scripts/test)
- [scripts/utils/validate-bedrock-wheel.py](scripts/utils/validate-bedrock-wheel.py)
- [scripts/utils/validate-httpx2-wheel.py](scripts/utils/validate-httpx2-wheel.py)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_httpx2.py](src/openai/_httpx2.py)
- [src/openai/_qs.py](src/openai/_qs.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [tests/conftest.py](tests/conftest.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/lib/test_bedrock_auth_conformance.py](tests/lib/test_bedrock_auth_conformance.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_extract_files.py](tests/test_extract_files.py)
- [tests/test_files.py](tests/test_files.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)
- [uv.lock](uv.lock)

</details>



This document explains how to customize the underlying HTTP client used by the OpenAI Python library. This includes configuring proxies, custom transports, connection pooling, and other advanced HTTP client settings. The library uses [httpx](https://www.python-httpx.org/) as its HTTP client library and exposes its configuration options through the `http_client` parameter.

For basic client configuration (API keys, timeouts, retries), see [Client Configuration](#2.1). For error handling and retry behavior, see [Error Handling and Retry Logic](#3.4).

**Scope**: This page covers HTTP-layer customization. It does not cover request/response data transformation, which is handled separately by the data transformation layer (see [Data Transformation Pipeline](#6.1)).

## HTTP Client Architecture

The OpenAI library provides both synchronous and asynchronous clients, each backed by an `httpx` HTTP client. The architecture allows complete control over HTTP behavior by accepting custom `httpx` client instances.

Title: HTTP Client Architecture and Data Flow
```mermaid
graph TB
    subgraph "Client_Initialization"
        USER["User Code"]
        SYNC_INIT["OpenAI(http_client=...)"]
        ASYNC_INIT["AsyncOpenAI(http_client=...)"]
    end
    
    subgraph "HTTP_Client_Layer"
        DEFAULT_SYNC["DefaultHttpxClient"]
        DEFAULT_ASYNC["DefaultAsyncHttpxClient"]
        CUSTOM_SYNC["Custom httpx.Client"]
        CUSTOM_ASYNC["Custom httpx.AsyncClient"]
        WRAPPER["SyncHttpxClientWrapper"]
    end
    
    subgraph "Base_Client_Classes"
        SYNC_API["SyncAPIClient"]
        ASYNC_API["AsyncAPIClient"]
        BASE["BaseClient[_HttpxClientT]"]
    end
    
    subgraph "HTTP_Configuration"
        TIMEOUT["Timeout Settings"]
        LIMITS["Connection Limits"]
        PROXY["Proxy Configuration"]
        TRANSPORT["Custom Transports"]
        AUTH["Custom Auth"]
    end
    
    USER --> SYNC_INIT
    USER --> ASYNC_INIT
    
    SYNC_INIT -->|"if http_client provided"| CUSTOM_SYNC
    SYNC_INIT -->|"if http_client=None"| WRAPPER
    WRAPPER --> DEFAULT_SYNC
    
    ASYNC_INIT -->|"if http_client provided"| CUSTOM_ASYNC
    ASYNC_INIT -->|"if http_client=None"| DEFAULT_ASYNC
    
    CUSTOM_SYNC --> SYNC_API
    WRAPPER --> SYNC_API
    DEFAULT_ASYNC --> ASYNC_API
    CUSTOM_ASYNC --> ASYNC_API
    
    SYNC_API --> BASE
    ASYNC_API --> BASE
    
    DEFAULT_SYNC --> TIMEOUT
    DEFAULT_SYNC --> LIMITS
    CUSTOM_SYNC --> PROXY
    CUSTOM_SYNC --> TRANSPORT
    CUSTOM_SYNC --> AUTH
```
Sources: [src/openai/_base_client.py:820-892](), [src/openai/_base_client.py:1497-1563]()

## Default HTTP Client Classes

The library provides helper classes that wrap `httpx` clients with sensible defaults. These classes configure the timeout, connection limits, and redirect behavior that the library expects.

### DefaultHttpxClient

The `DefaultHttpxClient` class is an alias (or subclass, depending on type-checking context) to `httpx.Client` with the following defaults:

| Setting | Default Value | Purpose |
|---------|---------------|---------|
| `timeout` | `httpx.Timeout(timeout=600, connect=5.0)` | 10-minute read timeout, 5-second connect timeout |
| `limits` | `httpx.Limits(max_connections=1000, max_keepalive_connections=100)` | Connection pooling limits |
| `follow_redirects` | `True` | Automatically follow HTTP redirects |

Title: DefaultHttpxClient Implementation Logic
```mermaid
graph LR
    IF["Type_Checking?"]
    RUNTIME["Runtime"]
    TYPECHECKING["Type_Checking"]
    
    ALIAS["DefaultHttpxClient = httpx.Client"]
    CLASS["class _DefaultHttpxClient(httpx.Client)"]
    
    IF -->|"Yes"| TYPECHECKING
    IF -->|"No"| RUNTIME
    
    TYPECHECKING --> ALIAS
    RUNTIME --> CLASS
    
    CLASS -->|"sets defaults"| DEFAULTS["timeout=DEFAULT_TIMEOUT<br/>limits=DEFAULT_CONNECTION_LIMITS<br/>follow_redirects=True"]
```

**Important**: When you provide your own `httpx.Client` instance, `httpx`'s defaults are used, not the library's defaults. To preserve the library's defaults when customizing, instantiate `DefaultHttpxClient` instead of `httpx.Client`.

Sources: [src/openai/_base_client.py:789-806](), [src/openai/_constants.py:84-91](), [src/openai/_client.py:142-145]()

### DefaultAsyncHttpxClient

The async equivalent `DefaultAsyncHttpxClient` provides the same defaults for `httpx.AsyncClient`.

Sources: [src/openai/_base_client.py:1467-1495]()

### SyncHttpxClientWrapper

Internally, when no `http_client` is provided to the synchronous `OpenAI` client, the library wraps the default client in `SyncHttpxClientWrapper`. This wrapper ensures the HTTP client is properly closed even if an exception occurs during cleanup.

Title: Client Wrapper Cleanup Logic
```mermaid
graph TB
    WRAPPER["SyncHttpxClientWrapper"]
    DEFAULT["DefaultHttpxClient"]
    DEL["__del__()"]
    CLOSE["close()"]
    
    WRAPPER -->|"extends"| DEFAULT
    WRAPPER -->|"implements"| DEL
    DEL -->|"calls if not closed"| CLOSE
    
    NOTE["Handles cleanup exceptions<br/>gracefully to avoid warnings"]
    DEL -.-> NOTE
```
Sources: [src/openai/_base_client.py:809-818]()

## Client Initialization Flow

The initialization flow determines whether to use a custom HTTP client or create a default one, and handles timeout precedence correctly.

Title: OpenAI Client Initialization Sequence
```mermaid
sequenceDiagram
    participant User
    participant OpenAI as "OpenAI.__init__"
    participant SyncAPIClient as "SyncAPIClient.__init__"
    participant DefaultClient as "SyncHttpxClientWrapper"
    participant CustomClient as "httpx.Client"
    
    User->>OpenAI: OpenAI(http_client=?, timeout=?)
    OpenAI->>SyncAPIClient: __init__(http_client, timeout)
    
    alt timeout not provided (NotGiven)
        SyncAPIClient->>SyncAPIClient: Check http_client.timeout
        alt http_client provided & has non-default timeout
            SyncAPIClient->>SyncAPIClient: timeout = http_client.timeout
        else
            SyncAPIClient->>SyncAPIClient: timeout = DEFAULT_TIMEOUT
        end
    end
    
    alt http_client is None
        SyncAPIClient->>DefaultClient: Create SyncHttpxClientWrapper
        DefaultClient-->>SyncAPIClient: wrapped client
    else http_client provided
        alt isinstance(http_client, httpx.Client)
            SyncAPIClient->>CustomClient: Use provided client
        else
            SyncAPIClient-->>User: TypeError: Invalid http_client
        end
    end
    
    SyncAPIClient-->>OpenAI: Initialized
    OpenAI-->>User: Client instance
```

**Type Validation**: The library validates that the provided `http_client` is actually an instance of `httpx.Client` (or `httpx.AsyncClient` for async). Passing the wrong type raises a `TypeError`.

Sources: [src/openai/_base_client.py:824-868](), [src/openai/_base_client.py:836-848](), [tests/test_client.py:311-319]()

## Proxy Configuration

Proxies are configured through the underlying `httpx` client. The library supports HTTP, HTTPS, and SOCKS proxies via `httpx`'s proxy parameter.

### Basic Proxy Setup

```python
from openai import OpenAI, DefaultHttpxClient

client = OpenAI(
    http_client=DefaultHttpxClient(
        proxy="http://my-proxy.example.com:8080"
    )
)
```

### Proxy Environment Variables

`httpx` automatically respects standard proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`). To disable this behavior, pass `trust_env=False` to the `httpx` client constructor.

Sources: [src/openai/_client.py:142-145](), [README.md:746-773]()

## Connection Pooling and Limits

Connection pooling configuration affects performance and resource usage. The library's defaults are tuned for typical API usage patterns.

### Default Connection Limits

The library sets these defaults via `DEFAULT_CONNECTION_LIMITS`:

| Limit | Default | Purpose |
|-------|---------|---------|
| `max_connections` | 1000 | Maximum total connections (active + idle) |
| `max_keepalive_connections` | 100 | Maximum idle connections to keep alive |

Title: Connection Pool Lifecycle
```mermaid
graph TB
    subgraph "Connection_Pool"
        ACTIVE["Active Connections<br/>(in use)"]
        IDLE["Idle Connections<br/>(keep-alive)"]
        TOTAL["Total = Active + Idle<br/>max: 1000"]
    end
    
    subgraph "Connection_Lifecycle"
        REQUEST["New Request"]
        REUSE["Reuse Idle Connection"]
        CREATE["Create New Connection"]
        RELEASE["Release to Idle Pool"]
        CLOSE["Close Excess Connections"]
    end
    
    REQUEST -->|"Idle available?"| REUSE
    REQUEST -->|"No idle available"| CREATE
    
    REUSE --> ACTIVE
    CREATE --> ACTIVE
    
    ACTIVE -->|"Request complete"| RELEASE
    RELEASE -->|"Under max_keepalive?"| IDLE
    RELEASE -->|"Over max_keepalive?"| CLOSE
    
    IDLE -->|"max_keepalive_connections=100"| TOTAL
    ACTIVE --> TOTAL
```

### Connection Tracking

The test suite verifies that connections are properly closed after retries to prevent leaks.

Sources: [src/openai/_constants.py:90](), [tests/test_client.py:732-763]()

## Timeout Customization

Timeouts can be configured at multiple levels with specific precedence rules.

### Timeout Precedence

The library determines the effective timeout using this precedence (highest to lowest):

1. **Per-request timeout**: `client.with_options(timeout=X)`
2. **Client initialization timeout**: `OpenAI(timeout=X)`
3. **Custom HTTP client timeout**: `OpenAI(http_client=httpx.Client(timeout=X))`
4. **Library default**: `DEFAULT_TIMEOUT` (600 seconds read, 5 seconds connect)

Title: Timeout Precedence Logic
```mermaid
graph TB
    PER_REQUEST["Per-request timeout<br/>with_options(timeout=X)"]
    CLIENT_INIT["Client init timeout<br/>OpenAI(timeout=X)"]
    HTTP_CLIENT["HTTP client timeout<br/>httpx.Client(timeout=X)"]
    DEFAULT["DEFAULT_TIMEOUT<br/>(600s read, 5s connect)"]
    
    DECISION{"Which_timeout<br/>to_use?"}
    
    DECISION -->|"1. Highest priority"| PER_REQUEST
    DECISION -->|"2. If not per-request"| CLIENT_INIT
    DECISION -->|"3. If not in init"| HTTP_CLIENT
    DECISION -->|"4. Fallback"| DEFAULT
    
    BUILD["_build_request()"]
    
    PER_REQUEST --> BUILD
    CLIENT_INIT --> BUILD
    HTTP_CLIENT --> BUILD
    DEFAULT --> BUILD
```

**Edge Case**: If you explicitly pass `httpx.Client(timeout=httpx.Timeout(5.0))` (which happens to equal `HTTPX_DEFAULT_TIMEOUT`), the library will not detect it as a custom timeout and will use `DEFAULT_TIMEOUT` instead.

Sources: [src/openai/_base_client.py:836-848](), [tests/test_client.py:280-310](), [src/openai/_base_client.py:122-128]()

## HTTP Client Lifecycle Management

### Context Manager Usage

Both clients support the context manager protocol for proper resource cleanup.

Title: Client Lifecycle and Cleanup
```mermaid
graph TB
    CLIENT["Client Instance"]
    CONTEXT["with client:"]
    DEL["__del__()"]
    EXPLICIT["client.close()"]
    
    subgraph "Cleanup_Paths"
        EXIT["__exit__()"]
        AEXIT["__aexit__()"]
        GC["Garbage Collection"]
    end
    
    CONTEXT --> EXIT
    EXIT --> EXPLICIT
    
    CLIENT -->|"async with"| AEXIT
    AEXIT --> EXPLICIT
    
    CLIENT -->|"del client or GC"| DEL
    DEL -->|"if not closed"| EXPLICIT
    
    EXPLICIT --> CLOSE["_client.close()"]
    
    NOTE["SyncHttpxClientWrapper.__del__<br/>handles cleanup exceptions"]
    DEL -.-> NOTE
```

Sources: [src/openai/_base_client.py:873-892](), [src/openai/_base_client.py:809-818](), [README.md:774-786]()

## Request Building and HTTP Client Integration

The library builds requests through a multi-stage pipeline that integrates with the custom HTTP client.

Title: Request Building Pipeline
```mermaid
graph TB
    OPTIONS["FinalRequestOptions"]
    PREPARE["_prepare_options()"]
    BUILD["_build_request()"]
    PREP_REQ["_prepare_request()"]
    SEND["_client.send()"]
    
    OPTIONS --> PREPARE
    PREPARE --> BUILD
    BUILD --> PREP_REQ
    PREP_REQ --> SEND
    
    subgraph "Build_Stage"
        HEADERS["Build headers"]
        URL["Prepare URL"]
        BODY["Serialize body"]
        CLIENT_BUILD["_client.build_request()"]
    end
    
    BUILD --> HEADERS
    HEADERS --> URL
    URL --> BODY
    BODY --> CLIENT_BUILD
    CLIENT_BUILD --> PREP_REQ
    
    NOTE1["• Merges custom_headers<br/>• Adds auth headers<br/>• Adds retry count"]
    HEADERS -.-> NOTE1
    
    NOTE2["• Hook for request mutation<br/>• Based on URL/method<br/>• Subclasses can override"]
    PREP_REQ -.-> NOTE2
```

### _prepare_request Hook

Subclasses can override `_prepare_request()` to mutate requests based on their properties. This hook is called after `_build_request()` but before the request is sent to the HTTP client. For example, the `BaseAzureClient` uses similar logic to adjust URLs for deployments.

Sources: [src/openai/_base_client.py:475-558](), [src/openai/_base_client.py:901-911](), [src/openai/lib/azure.py:68-79]()

---

# Page: Development and Contribution

# Development and Contribution

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.devcontainer/Dockerfile](.devcontainer/Dockerfile)
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json)
- [.github/codex/prompts/python-version-review.md](.github/codex/prompts/python-version-review.md)
- [.github/codex/python-version-review-config.toml](.github/codex/python-version-review-config.toml)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [.github/workflows/create-releases.yml](.github/workflows/create-releases.yml)
- [.github/workflows/publish-pypi.yml](.github/workflows/publish-pypi.yml)
- [.github/workflows/python-version-review.yml](.github/workflows/python-version-review.yml)
- [.python-version](.python-version)
- [AGENTS.md](AGENTS.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [PYTHON_VERSION_POLICY.md](PYTHON_VERSION_POLICY.md)
- [examples/realtime/push_to_talk_app.py](examples/realtime/push_to_talk_app.py)

</details>



This document provides an overview of the development workflow, tooling, and contribution process for the OpenAI Python SDK. It covers the complete lifecycle from setting up a local development environment through testing, code quality checks, and automated release processes.

For detailed information on specific topics:
- Development environment setup and tooling: see [Development Environment Setup](#8.1)
- Testing infrastructure and practices: see [Testing Framework and Practices](#8.2)
- Code quality tools and configurations: see [Code Quality and Type Checking](#8.3)
- CI/CD workflows and release automation: see [CI/CD Pipeline and Release Process](#8.4)

## Development Workflow Overview

The SDK uses a modern Python development stack centered on **Rye 0.44.0** for dependency management and package building. All configuration is consolidated in `pyproject.toml`, which defines project metadata, dependencies, development tools, and their settings.

### Core Development Tools

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **Rye 0.44.0** | Package manager, virtual environment management | [CONTRIBUTING.md:8-20]() |
| **pytest** | Test framework with async support | [.github/workflows/ci.yml:144]() |
| **ruff** | Code formatting and linting | [CONTRIBUTING.md:105-113]() |
| **release-please** | Automated release management | [.github/workflows/create-releases.yml:21-25]() |

### Development Lifecycle

```mermaid
graph TB
    subgraph "Local Development"
        CLONE["git clone<br/>openai/openai-python"]
        RYE_SYNC["rye sync --all-features<br/>(Install dependencies)"]
        EDIT["Edit source code<br/>src/openai/**"]
        LOCAL_TEST["./scripts/test<br/>(pytest)"]
        LOCAL_LINT["./scripts/lint<br/>(ruff + typecheckers)"]
    end
    
    subgraph "Commit & Push"
        COMMIT["git commit<br/>(Conventional format)"]
        PUSH["git push origin<br/>feature-branch"]
    end
    
    subgraph "CI Pipeline (.github/workflows/ci.yml)"
        TRIGGER["CI Triggered"]
        LINT_JOB["lint job<br/>./scripts/lint"]
        BUILD_JOB["build job<br/>rye build"]
        TEST_JOB["test job<br/>./scripts/test"]
        UPLOAD["Upload artifact<br/>to Stainless Storage"]
    end
    
    subgraph "Pull Request"
        PR["Create Pull Request"]
        REVIEW["Code Review"]
        MERGE["Merge to main"]
    end
    
    subgraph "Release Automation (.github/workflows/create-releases.yml)"
        RELEASE_PLEASE["release-please<br/>Analyze commits<br/>Update CHANGELOG.md"]
        BUILD_RELEASE["rye build"]
        PUBLISH["pypa/gh-action-pypi-publish<br/>to PyPI"]
    end
    
    CLONE --> RYE_SYNC
    RYE_SYNC --> EDIT
    EDIT --> LOCAL_TEST
    LOCAL_TEST --> LOCAL_LINT
    LOCAL_LINT --> COMMIT
    COMMIT --> PUSH
    
    PUSH --> TRIGGER
    TRIGGER --> LINT_JOB
    TRIGGER --> BUILD_JOB
    TRIGGER --> TEST_JOB
    BUILD_JOB --> UPLOAD
    
    PUSH --> PR
    PR --> REVIEW
    LINT_JOB --> REVIEW
    TEST_JOB --> REVIEW
    REVIEW --> MERGE
    
    MERGE --> RELEASE_PLEASE
    RELEASE_PLEASE --> BUILD_RELEASE
    BUILD_RELEASE --> PUBLISH
```

**Sources:** [.github/workflows/ci.yml:23-145](), [CONTRIBUTING.md:8-127](), [.github/workflows/create-releases.yml:1-79]()

## Project Configuration Structure

The project uses `rye` for dependency orchestration. While most of the SDK is generated, manual modifications are persisted in `src/openai/lib/` and `examples/` [CONTRIBUTING.md:42-48]().

### Dependency Management

The project manages dependencies via Rye, ensuring reproducible environments.
- **Syncing:** `rye sync --all-features` [CONTRIBUTING.md:19]().
- **Bootstrapping:** `./scripts/bootstrap` [CONTRIBUTING.md:13]().
- **Build System:** Uses `rye build` to generate `.tar.gz` and `.whl` files [CONTRIBUTING.md:80]().

**Sources:** [CONTRIBUTING.md:1-89]()

## Development Environment Options

### Option 1: Dev Container (Recommended)

A pre-configured environment is provided for VS Code users:
- **Base Image:** `mcr.microsoft.com/vscode/devcontainers/python:0-3.9` [.devcontainer/Dockerfile:2]().
- **Tooling:** Rye 0.44.0 is pre-installed [.devcontainer/Dockerfile:6]().
- **Post-Start:** Automatically runs `rye sync --all-features` [.devcontainer/devcontainer.json:10]().

### Option 2: Local Development with Rye

Install Rye manually and run the bootstrap script to provision the environment [CONTRIBUTING.md:8-20](). The SDK follows a strict Python version policy, currently supporting Python 3.10 through 3.14 [PYTHON_VERSION_POLICY.md:65-72]().

**Sources:** [.devcontainer/Dockerfile:1-10](), [.devcontainer/devcontainer.json:1-44](), [CONTRIBUTING.md:8-39](), [PYTHON_VERSION_POLICY.md:1-83]()

## Testing and Quality Assurance

### Testing Framework

Tests are executed using `pytest`. The suite includes specific validations for different HTTP clients like `httpx` and `httpx2` [.github/workflows/ci.yml:174-179]().

| Script | Purpose |
|--------|---------|
| `./scripts/mock` | Starts the mock server against the OpenAPI spec [CONTRIBUTING.md:96](). |
| `./scripts/test` | Runs the test suite using the configured environment [.github/workflows/ci.yml:144](). |
| `./scripts/lint` | Runs ruff and type checking [CONTRIBUTING.md:111](). |

**Sources:** [.github/workflows/ci.yml:110-181](), [CONTRIBUTING.md:91-119]()

## CI/CD Pipeline and Releases

### Continuous Integration

The CI workflow in `.github/workflows/ci.yml` performs:
1. **Linting:** Runs `./scripts/lint` [.github/workflows/ci.yml:41]().
2. **Building:** Executes `rye build` [.github/workflows/ci.yml:64]().
3. **Testing:** Executes `./scripts/test` across supported Python versions [.github/workflows/ci.yml:144]().
4. **Artifact Upload:** Uploads built wheels for internal tracking [.github/workflows/ci.yml:100-108]().

### Release Process

Releases are managed via `release-please` automation [.github/workflows/create-releases.yml:21-25]().
- **PyPI Publishing:** Handled by `pypa/gh-action-pypi-publish` using Trusted Publishing (OIDC) [.github/workflows/create-releases.yml:77-79]().
- **Manual Release:** Can be triggered via the `Publish PyPI` workflow dispatch [.github/workflows/publish-pypi.yml:3-5]().

### Version Policy Monitoring

The SDK includes an automated monthly review process to assess Python version support:

```mermaid
sequenceDiagram
    participant GH as "GitHub Actions"
    participant PEPS as "peps.python.org"
    participant PYPI as "pypistats.org"
    participant CX as "Codex Agent"

    GH->>PEPS: Fetch release-cycle.json
    GH->>PYPI: Fetch usage stats for 'openai'
    GH->>CX: Pass snapshots + policy docs
    Note over CX: Assess drift & EOL status
    CX-->>GH: Report (Action Required / No Action)
    alt Action Required
        GH->>GH: Open/Refresh Maintenance Issue
    end
```

**Sources:** [.github/workflows/ci.yml:1-181](), [.github/workflows/create-releases.yml:1-79](), [.github/workflows/publish-pypi.yml:1-60](), [.github/workflows/python-version-review.yml:1-190](), [PYTHON_VERSION_POLICY.md:51-59]()

---

# Page: Development Environment Setup

# Development Environment Setup

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.devcontainer/Dockerfile](.devcontainer/Dockerfile)
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json)
- [.github/codex/prompts/python-version-review.md](.github/codex/prompts/python-version-review.md)
- [.github/codex/python-version-review-config.toml](.github/codex/python-version-review-config.toml)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [.github/workflows/create-releases.yml](.github/workflows/create-releases.yml)
- [.github/workflows/publish-pypi.yml](.github/workflows/publish-pypi.yml)
- [.github/workflows/python-version-review.yml](.github/workflows/python-version-review.yml)
- [.python-version](.python-version)
- [AGENTS.md](AGENTS.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [PYTHON_VERSION_POLICY.md](PYTHON_VERSION_POLICY.md)
- [examples/realtime/push_to_talk_app.py](examples/realtime/push_to_talk_app.py)

</details>



This page explains how to set up a local development environment for contributing to the OpenAI Python SDK. It covers installing the Rye package manager, syncing dependencies, using dev containers, and verifying your setup.

## Overview

The OpenAI Python SDK uses **Rye 0.44.0** as its primary tool for dependency management, virtual environment creation, and task execution [.github/workflows/ci.yml:34](), [.devcontainer/Dockerfile:6](). The project supports a range of Python versions from 3.10 through 3.14 [PYTHON_VERSION_POLICY.md:70-71]().

Development is supported through two primary paths:
- **Local setup**: Using Rye directly on a host machine [CONTRIBUTING.md:9-30]().
- **Dev container**: Using a pre-configured Docker environment with VS Code [.devcontainer/devcontainer.json:1-43]().

Sources: [.github/workflows/ci.yml:34](), [.devcontainer/Dockerfile:6](), [PYTHON_VERSION_POLICY.md:70-71](), [CONTRIBUTING.md:9-30]()

## Development Environment Architecture

The following diagram bridges the setup methods with the specific tools and scripts defined in the codebase.

**Setup Path to Code Entity Mapping**
```mermaid
graph TB
    subgraph "Developer Machine"
        DEV_CHOICE["Choose Setup Method"]
        
        subgraph "Local Setup Path"
            BOOTSTRAP["scripts/bootstrap<br/>Shell Script"]
            RYE_SYNC["rye sync --all-features<br/>Dependency Resolution"]
            LOCAL_VENV[".venv/<br/>Virtual Environment"]
        end
        
        subgraph "Dev Container Path"
            DEVCONTAINER_JSON[".devcontainer/devcontainer.json"]
            DOCKERFILE[".devcontainer/Dockerfile<br/>Python 3.9 Base"]
            CONTAINER_VENV[".venv/<br/>In-Container Env"]
        end
    end
    
    subgraph "Configuration Files"
        PYPROJECT["pyproject.toml<br/>Project Metadata"]
        LOCK_FILE["requirements-dev.lock<br/>Pinned Dependencies"]
        VERSION_FILE[".python-version<br/>3.10.16"]
    end
    
    subgraph "Quality & Build Scripts"
        LINT_SCRIPT["./scripts/lint<br/>Linting Entrypoint"]
        TEST_SCRIPT["./scripts/test<br/>Test Entrypoint"]
        BUILD_CMD["rye build<br/>Artifact Generation"]
    end
    
    DEV_CHOICE --> BOOTSTRAP
    DEV_CHOICE --> DEVCONTAINER_JSON
    
    BOOTSTRAP --> RYE_SYNC
    RYE_SYNC --> LOCAL_VENV
    
    DEVCONTAINER_JSON --> DOCKERFILE
    DOCKERFILE --> CONTAINER_VENV
    
    PYPROJECT --> RYE_SYNC
    LOCK_FILE --> RYE_SYNC
    VERSION_FILE --> RYE_SYNC
    
    LOCAL_VENV --> LINT_SCRIPT
    LOCAL_VENV --> TEST_SCRIPT
    LOCAL_VENV --> BUILD_CMD
    CONTAINER_VENV --> LINT_SCRIPT
```

Sources: [.devcontainer/Dockerfile:1-10](), [.devcontainer/devcontainer.json:1-43](), [CONTRIBUTING.md:1-39](), [.python-version:1](), [.github/workflows/ci.yml:38-41]()

## Prerequisites

| Requirement | Version / Policy | Notes |
|------------|----------------|-------|
| Python | 3.10+ | Minimum supported version is 3.10 [PYTHON_VERSION_POLICY.md:67]() |
| Rye | 0.44.0 | Pinned version for consistency [.github/workflows/ci.yml:34]() |
| Docker | Latest | Required for Dev Container path |
| API Key | `OPENAI_API_KEY` | Required for running examples and some tests [examples/realtime/push_to_talk_app.py:4]() |

Sources: [PYTHON_VERSION_POLICY.md:67](), [.github/workflows/ci.yml:34](), [examples/realtime/push_to_talk_app.py:4]()

## Local Setup with Rye

### Installation and Bootstrapping

The project recommends using `rye` to provision the environment automatically.

1. **Automatic Setup**: Run the provided bootstrap script.
   ```sh
   ./scripts/bootstrap
   ```
   This script automates environment configuration and dependency syncing [CONTRIBUTING.md:13]().

2. **Manual Setup**: If you prefer manual steps, install Rye 0.44.0 and run:
   ```sh
   rye sync --all-features
   ```
   The `--all-features` flag ensures that all optional dependency groups (like `realtime`) are installed [CONTRIBUTING.md:19](), [examples/realtime/push_to_talk_app.py:20]().

### Virtual Environment Management

Rye creates a virtual environment in the `.venv` directory. You can interact with it in two ways:
- **Prefixing commands**: `rye run python script.py` [CONTRIBUTING.md:22]().
- **Activation**: `source .venv/bin/activate` [CONTRIBUTING.md:26]().

### Alternative: Setup Without Rye

If you choose not to use Rye, you must ensure your Python version matches `.python-version` (currently 3.10.16) and install dependencies via the lock file:
```sh
pip install -r requirements-dev.lock
```
Sources: [CONTRIBUTING.md:34-38](), [.python-version:1]()

## Dev Container Setup

The repository includes a `.devcontainer` configuration for an isolated development environment in VS Code.

**Dev Container Entity Relationship**
```mermaid
graph LR
    subgraph "Host OS"
        VSCODE["VS Code"]
    end
    
    subgraph "Docker Engine"
        subgraph "OpenAI Dev Container"
            BASE_IMAGE["mcr.microsoft.com/vscode/devcontainers/python:0-3.9"]
            RYE_BIN["/home/vscode/.rye/shims/rye"]
            POST_START["postStartCommand:<br/>rye sync --all-features"]
            VENV_PATH[".venv/bin/python"]
        end
    end
    
    VSCODE -->|.devcontainer/devcontainer.json| BASE_IMAGE
    BASE_IMAGE -->|RUN curl| RYE_BIN
    RYE_BIN -->|Executes| POST_START
    POST_START -->|Creates| VENV_PATH
    VSCODE -->|python.defaultInterpreterPath| VENV_PATH
```

Sources: [.devcontainer/Dockerfile:1-10](), [.devcontainer/devcontainer.json:1-43]()

### Configuration Details
- **Base Image**: Uses Python 3.9 as the build variant [.devcontainer/Dockerfile:1-2]().
- **Tooling**: Automatically installs Rye 0.44.0 and configures the shell PATH [.devcontainer/Dockerfile:6-7]().
- **Automation**: The `postStartCommand` ensures the environment is synced every time the container starts [.devcontainer/devcontainer.json:10]().
- **VS Code Settings**: Configures the Python extension to use the internal `.venv` and enables basic type checking [.devcontainer/devcontainer.json:19-21]().

## Verification and Quality Tools

After setup, verify your environment using the following scripts:

### Linting and Formatting
The SDK uses `ruff` and `black` for code quality [CONTRIBUTING.md:105-106]().
- **Lint**: `./scripts/lint` [CONTRIBUTING.md:111]()
- **Format**: `./scripts/format` [CONTRIBUTING.md:117]()

### Testing
Tests typically require a mock server to be running:
1. **Start Mock Server**: `./scripts/mock` [CONTRIBUTING.md:96]()
2. **Run Tests**: `./scripts/test` [CONTRIBUTING.md:100]()

### Build Verification
To verify the package builds correctly for distribution:
```sh
rye build
```
This command generates `.tar.gz` and `.whl` files in the `dist/` directory [CONTRIBUTING.md:73-80]().

Sources: [CONTRIBUTING.md:73-117](), [.github/workflows/ci.yml:41-42](), [.github/workflows/ci.yml:64]()

---

# Page: Testing Framework and Practices

# Testing Framework and Practices

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Brewfile](Brewfile)
- [examples/httpx2_client.py](examples/httpx2_client.py)
- [requirements-dev.lock](requirements-dev.lock)
- [requirements.lock](requirements.lock)
- [scripts/bootstrap](scripts/bootstrap)
- [scripts/format](scripts/format)
- [scripts/lint](scripts/lint)
- [scripts/mock](scripts/mock)
- [scripts/test](scripts/test)
- [scripts/utils/validate-bedrock-wheel.py](scripts/utils/validate-bedrock-wheel.py)
- [scripts/utils/validate-httpx2-wheel.py](scripts/utils/validate-httpx2-wheel.py)
- [src/openai/_httpx2.py](src/openai/_httpx2.py)
- [src/openai/_qs.py](src/openai/_qs.py)
- [src/openai/lib/_parsing/__init__.py](src/openai/lib/_parsing/__init__.py)
- [tests/conftest.py](tests/conftest.py)
- [tests/lib/chat/test_completions.py](tests/lib/chat/test_completions.py)
- [tests/lib/chat/test_completions_streaming.py](tests/lib/chat/test_completions_streaming.py)
- [tests/lib/responses/__init__.py](tests/lib/responses/__init__.py)
- [tests/lib/responses/test_responses.py](tests/lib/responses/test_responses.py)
- [tests/lib/snapshots.py](tests/lib/snapshots.py)
- [tests/lib/test_bedrock_auth_conformance.py](tests/lib/test_bedrock_auth_conformance.py)
- [tests/lib/utils.py](tests/lib/utils.py)
- [tests/test_extract_files.py](tests/test_extract_files.py)
- [tests/test_files.py](tests/test_files.py)
- [uv.lock](uv.lock)

</details>



This document describes the testing infrastructure, tools, and practices used in the OpenAI Python library. It covers the pytest-based testing framework, HTTP mocking strategies, snapshot testing, and guidelines for writing and running tests.

For information about code quality tooling (linting and type checking), see **8.3 Code Quality and Type Checking**. For CI/CD workflows, see **8.4 CI/CD Pipeline and Release Process**.

---

## Overview

The library uses a comprehensive testing framework built on `pytest` with specialized tools for HTTP mocking, snapshot testing, and asynchronous test execution. Tests are organized by API resource and feature area, with support for both mocked testing (default) and live API testing (opt-in).

**Key Characteristics:**
- **Framework**: `pytest` with async support via `pytest-asyncio` [requirements-dev.lock:173, 177]().
- **HTTP Mocking**: `respx` library for request interception [requirements-dev.lock:191]().
- **Snapshot Testing**: `inline-snapshot` for response validation and regression testing [requirements-dev.lock:111]().
- **Parallel Execution**: `pytest-xdist` for concurrent test runs [requirements-dev.lock:178]().
- **Live Testing**: Optional real API calls via environment flag `OPENAI_LIVE=1` [tests/lib/chat/test_completions.py:28]().
- **Mock Server**: Local `steady` server based on OpenAPI spec [scripts/mock:29-60]().

Sources: [requirements-dev.lock:111](), [requirements-dev.lock:173](), [requirements-dev.lock:177](), [requirements-dev.lock:178](), [requirements-dev.lock:191](), [scripts/mock:29-60](), [tests/lib/chat/test_completions.py:28]()

---

## Testing Framework Architecture

The following diagram bridges the high-level testing concepts to the specific code entities and scripts used in the SDK.

**Testing System Entity Map**
```mermaid
graph TB
    subgraph "Test Execution Layer"
        pytest["pytest (Test Runner)"]
        pytest_asyncio["pytest-asyncio (Async Plugin)"]
        pytest_xdist["pytest-xdist (Parallelism)"]
        nox["nox (Multi-env Runner)"]
    end
    
    subgraph "HTTP Mocking & Validation"
        respx["respx.MockRouter (Request Interceptor)"]
        steady["Steady CLI (OpenAPI Mock Server)"]
        httpx2_mock["enable_httpx2_respx (Custom Transport Mock)"]
    end
    
    subgraph "Snapshot & Assertion Layer"
        inline_snapshot["inline-snapshot (Snapshot Engine)"]
        dirty_equals["dirty-equals (Flexible Assertions)"]
        make_snapshot_request["make_snapshot_request (Helper)"]
    end
    
    subgraph "Client Fixtures"
        conftest["tests/conftest.py"]
        client_fixture["client fixture (OpenAI)"]
        async_client_fixture["async_client fixture (AsyncOpenAI)"]
    end
    
    pytest --> pytest_asyncio
    pytest --> pytest_xdist
    nox --> pytest
    
    pytest --> respx
    pytest --> steady
    respx --> httpx2_mock
    
    pytest --> inline_snapshot
    inline_snapshot --> make_snapshot_request
    
    pytest --> conftest
    conftest --> client_fixture
    conftest --> async_client_fixture
```
Sources: [requirements-dev.lock:111](), [requirements-dev.lock:137](), [requirements-dev.lock:173-178](), [requirements-dev.lock:191](), [tests/conftest.py:68-119](), [tests/lib/snapshots.py:1-20](), [tests/_httpx2_respx.py:1-10]()

**Testing Framework Components**

| Component | Purpose | Code Entities |
|-----------|---------|---------------|
| **pytest** | Primary test discovery and execution engine. | `pytest` [requirements-dev.lock:173]() |
| **pytest-asyncio** | Handles async test loops and fixtures. | `pytest_asyncio` [requirements-dev.lock:177]() |
| **respx** | Mocks `httpx` and `httpx2` calls without a real server. | `respx.MockRouter` [requirements-dev.lock:191]() |
| **inline-snapshot** | Manages inline and external snapshots for API responses. | `snapshot()`, `external()` [requirements-dev.lock:111]() |
| **Steady** | Mock server validating requests against OpenAPI specs. | `@stdy/cli` [scripts/mock:36]() |
| **nox** | Runs tests across different Pydantic versions. | `nox` [requirements-dev.lock:137]() |

Sources: [requirements-dev.lock:111](), [requirements-dev.lock:137](), [requirements-dev.lock:173](), [requirements-dev.lock:177](), [requirements-dev.lock:191](), [scripts/mock:36]()

---

## Test Configuration and Fixtures

### Pytest Configuration

The testing environment is configured via `tests/conftest.py`. It handles automatic async marking and provides client fixtures.

**Async Test Automation**: The `pytest_collection_modifyitems` hook automatically applies `pytest.mark.asyncio(loop_scope="session")` to all async tests [tests/conftest.py:29-33]().

**Client Fixtures**:
- `client`: A session-scoped `OpenAI` client pointing to the mock server (default: `http://127.0.0.1:4010`) [tests/conftest.py:68-83]().
- `async_client`: A session-scoped `AsyncOpenAI` client. It can be parameterized to use `httpx`, `httpx2`, or `aiohttp` backends [tests/conftest.py:86-119]().

```python
@pytest.fixture(scope="session")
def client(request: FixtureRequest) -> Iterator[OpenAI]:
    # ... setup logic ...
    with OpenAI(
        base_url=base_url,
        api_key=api_key,
        _strict_response_validation=strict,
        http_client=http_client,
    ) as client:
        yield client
```
Sources: [tests/conftest.py:29-33](), [tests/conftest.py:68-119]()

### Mock Server (Steady)

The SDK uses `steady` to provide a local mock server that validates requests against the OpenAI OpenAPI spec.

- **Startup**: The `./scripts/mock` script starts the server [scripts/mock:29-60]().
- **Health Check**: The test runner waits for `/_x-steady/health` before starting execution [scripts/test:12-14]().
- **Validation**: It uses bracket formatting for arrays and objects in queries and forms [scripts/mock:36]().

Sources: [scripts/mock:29-60](), [scripts/test:12-14]()

---

## Snapshot Testing Practices

The SDK extensively uses `inline-snapshot` to verify that API responses are parsed correctly into Pydantic models.

**Data Flow: Snapshot Generation**
```mermaid
graph LR
    subgraph "Snapshot Workflow"
        test_fn["Test Function"]
        make_snap["make_snapshot_request"]
        api_call["API Client Call"]
        respx_mock["RESPX Mock / Live API"]
    end
    
    test_fn --> make_snap
    make_snap --> api_call
    api_call --> respx_mock
    respx_mock -- JSON Response --> make_snap
    make_snap -- Parsed Model --> inline_snap["inline_snapshot.snapshot()"]
```
Sources: [tests/lib/chat/test_completions.py:33-49](), [tests/lib/snapshots.py:1-20]()

### Updating Snapshots
Snapshots can be updated from the live API by setting the `OPENAI_LIVE` environment variable and running pytest with the `--inline-snapshot=fix` flag [tests/lib/chat/test_completions.py:28]().

### Streaming Snapshots
For streaming responses, the SDK uses `_make_stream_snapshot_request` which captures chunks and final states into binary external snapshots [tests/lib/chat/test_completions_streaming.py:48-61]().

Sources: [tests/lib/chat/test_completions.py:28-49](), [tests/lib/chat/test_completions_streaming.py:48-61]()

---

## Multi-Backend and Version Testing

### HTTP Client Backends
The test suite validates multiple HTTP backends via the `OPENAI_TEST_HTTP_CLIENT` environment variable:
- `httpx`: The default backend [tests/conftest.py:52]().
- `httpx2`: A modern alternative backend [tests/conftest.py:73]().
- `aiohttp`: Supported for async operations [tests/conftest.py:104]().

**Compatibility Note**: Tests using `aiohttp` are skipped when `respx_mock` is required, as `respx` does not support the `aiohttp` adapter [tests/conftest.py:35-48]().

### Pydantic Compatibility
The SDK supports Pydantic v1 and v2. The `./scripts/test` script ensures both are tested:
1. Runs standard tests (usually v2) [scripts/test:62]().
2. Runs `nox -s test-pydantic-v1` to specifically test the v1 compatibility layer [scripts/test:65]().

Sources: [scripts/test:62-65](), [tests/conftest.py:35-52](), [tests/conftest.py:73-104]()

---

## Test Execution Scripts

The project provides several bash scripts to manage the testing lifecycle:

| Script | Purpose |
|--------|---------|
| `./scripts/test` | Main entry point. Starts the mock server and runs pytest and nox [scripts/test:1-66](). |
| `./scripts/mock` | Starts the Steady OpenAPI mock server [scripts/mock:1-61](). |
| `./scripts/bootstrap` | Installs Python dependencies using `rye sync` [scripts/bootstrap:22-27](). |
| `./scripts/lint` | Runs `ruff` for linting and formatting [scripts/lint:1-13](). |

Sources: [scripts/bootstrap:22-27](), [scripts/lint:1-13](), [scripts/mock:1-61](), [scripts/test:1-66]()

---

# Page: Code Quality and Type Checking

# Code Quality and Type Checking

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/detect-breaking-changes.yml](.github/workflows/detect-breaking-changes.yml)
- [.release-please-manifest.json](.release-please-manifest.json)
- [CHANGELOG.md](CHANGELOG.md)
- [pyproject.toml](pyproject.toml)
- [scripts/detect-breaking-changes](scripts/detect-breaking-changes)
- [scripts/detect-breaking-changes.py](scripts/detect-breaking-changes.py)
- [scripts/pyrightconfig.breaking-changes.json](scripts/pyrightconfig.breaking-changes.json)
- [scripts/run-pyright](scripts/run-pyright)
- [src/openai/_version.py](src/openai/_version.py)

</details>



This document covers the code quality and type checking infrastructure used in the OpenAI Python SDK. It explains the configuration and usage of linting tools (Ruff), type checkers (Pyright and Mypy), and how these tools are integrated into the development workflow and CI pipeline.

For information about the testing framework and test execution, see [8.2 Testing Framework and Practices](). For details about the CI/CD pipeline and release automation, see [8.4 CI/CD Pipeline and Release Process]().

## Overview

The OpenAI Python SDK enforces strict code quality standards through automated tooling. Three primary tools work together to maintain code quality:

Title: Code Quality Toolchain Architecture
```mermaid
graph TB
    subgraph "Configuration Source"
        PYPROJECT["pyproject.toml<br/>[tool.ruff]<br/>[tool.pyright]<br/>[tool.mypy]"]
    end
    
    subgraph "Code Quality Tools"
        RUFF["Ruff<br/>Linter + Formatter"]
        PYRIGHT["Pyright<br/>Type Checker"]
        MYPY["Mypy<br/>Type Checker"]
    end
    
    subgraph "Execution Methods"
        SCRIPTS["rye run lint<br/>rye run format<br/>rye run typecheck"]
        SHELL_SCRIPTS["scripts/run-pyright<br/>scripts/detect-breaking-changes"]
    end
    
    subgraph "Target Files"
        SRC["src/openai/**/*.py"]
        TESTS["tests/**/*.py"]
        EXAMPLES["examples/**/*.py"]
        SCRIPTS_DIR["scripts/**/*.py"]
    end
    
    PYPROJECT --> RUFF
    PYPROJECT --> PYRIGHT
    PYPROJECT --> MYPY
    
    RUFF --> SCRIPTS
    PYRIGHT --> SCRIPTS
    MYPY --> SCRIPTS
    
    SCRIPTS --> SHELL_SCRIPTS
    
    RUFF --> SRC
    RUFF --> TESTS
    PYRIGHT --> SRC
    MYPY --> SRC
```

**Sources:** [pyproject.toml:88-116](), [scripts/run-pyright:1-8](), [scripts/detect-breaking-changes:1-25]()

## Ruff Configuration

Ruff serves as both the linter and code formatter for the project. It replaces multiple tools with a single fast implementation.

### Basic Settings

The base Ruff configuration is defined in `[tool.ruff]`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `line-length` | 120 | Maximum characters per line |
| `output-format` | "grouped" | Groups errors by file for readability |
| `target-version` | "py310" | Compatibility checks target Python 3.10+ |

**Sources:** [pyproject.toml:255-257]()

### Enabled Linting Rules

The `[tool.ruff.lint]` section specifies which rule categories are enabled:

Title: Ruff Lint Rule Selection
```mermaid
graph LR
    subgraph "Ruff Rule Categories"
        ISORT["I - isort<br/>Import sorting"]
        BUGBEAR["B - bugbear<br/>Bug prevention"]
        F401["F401<br/>Remove unused imports"]
        FA102["FA102<br/>Future annotations"]
        E722["E722<br/>Bare except"]
        ARG["ARG<br/>Unused arguments"]
    end
    
    PYPROJECT["pyproject.toml<br/>[tool.ruff.lint]<br/>select=[...]"] --> ISORT
    PYPROJECT --> BUGBEAR
    PYPROJECT --> F401
    PYPROJECT --> FA102
    PYPROJECT --> E722
    PYPROJECT --> ARG
```

**Sources:** [pyproject.toml:262-275]()

The configuration includes specific rules:

- **I (isort)**: Enforces import ordering [pyproject.toml:265]().
- **B (bugbear)**: Detects common Python bugs and design issues [pyproject.toml:267]().
- **F401**: Automatically removes unused imports [pyproject.toml:269]().
- **FA102**: Requires `from __future__ import annotations` for forward reference support [pyproject.toml:271]().
- **E722**: Disallows bare `except:` statements [pyproject.toml:273]().

### Per-File Overrides

Specific rules are relaxed for directories where they are less relevant:

- **Tests, Scripts, Examples**: Print statements (`T201`, `T203`) are allowed in `bin/**.py`, `scripts/**.py`, `tests/**.py`, and `examples/**.py`.
- **Global Ignores**: Rule `B006` (mutable default arguments) is ignored globally.

**Sources:** [pyproject.toml:277-300]()

## Pyright Type Checking

Pyright is the primary type checker for the SDK, configured to use the strictest possible settings.

### Core Configuration

Title: Pyright Configuration Logic
```mermaid
graph TB
    subgraph "Pyright Configuration"
        CONFIG["[tool.pyright]<br/>pyproject.toml:168-192"]
        
        MODE["typeCheckingMode = 'strict'"]
        PYTHON["pythonVersion = '3.10'"]
        EXCLUDE["exclude = [...]"]
        
        IMPLICIT["reportImplicitOverride = true"]
        OVERLAP["reportOverlappingOverload = false"]
        CYCLES["reportImportCycles = false"]
        PRIVATE["reportPrivateUsage = false"]
    end
    
    CONFIG --> MODE
    CONFIG --> PYTHON
    CONFIG --> EXCLUDE
    CONFIG --> IMPLICIT
    CONFIG --> OVERLAP
    CONFIG --> CYCLES
    CONFIG --> PRIVATE
    
    MODE --> STRICT["Enables all strict checks"]
    PYTHON --> COMPAT["Minimum Python 3.10 syntax"]
```

**Sources:** [pyproject.toml:168-192]()

### Key Settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| `typeCheckingMode` | `"strict"` | Enables all available type checks |
| `pythonVersion` | `"3.10"` | Matches minimum required Python version [pyproject.toml:22]() |
| `reportImplicitOverride` | `true` | Requires explicit `@override` decorator |
| `reportOverlappingOverload` | `false` | Allows intentional overload overlaps |
| `reportImportCycles` | `false` | Permits circular imports |
| `reportPrivateUsage` | `false` | Allows access to `_private` members |

**Sources:** [pyproject.toml:168-192]()

### Excluded Directories

Pyright skips type checking for specific paths, primarily examples with inline `uv` script dependencies:

```python
# From pyproject.toml:175-185
exclude = [
    "_dev",
    ".venv",
    ".nox",
    ".git",
    "examples/realtime/audio_util.py",
    "examples/realtime/push_to_talk_app.py"
]
```

**Sources:** [pyproject.toml:175-185]()

### Running Pyright

Pyright is invoked via Rye scripts or the `scripts/run-pyright` wrapper:

```bash
# Run all type checks (Pyright + Mypy)
rye run typecheck

# Run only Pyright
rye run typecheck:pyright

# Verify the package exports types correctly
rye run typecheck:verify-types
```

**Sources:** [pyproject.toml:109-116](), [scripts/run-pyright:1-8]()

## Mypy Type Checking

Mypy serves as a secondary type checker, providing additional validation and catching edge cases.

### Configuration Strategy

The Mypy configuration at `[tool.mypy]` is set to strict mode with specific exclusions:

Title: Mypy Configuration and Exclusions
```mermaid
graph TB
    subgraph "Mypy Configuration Flow"
        CONFIG["[tool.mypy]<br/>pyproject.toml:193-253"]
        
        STRICT_OPTS["Strict Options:<br/>- strict_equality<br/>- check_untyped_defs<br/>- disallow_untyped_defs<br/>- disallow_any_generics"]
        
        EXCLUDE["Excluded Files:<br/>- src/openai/_files.py<br/>- tests/.*<br/>- examples/realtime/*"]
        
        DISABLED["Disabled Checks:<br/>- warn_unused_ignores<br/>- warn_redundant_casts"]
    end
    
    CONFIG --> STRICT_OPTS
    CONFIG --> EXCLUDE
    CONFIG --> DISABLED
    
    DISABLED --> REASON["Disabled to avoid<br/>conflicts with Pyright"]
```

**Sources:** [pyproject.toml:193-253]()

### Strict Mode Settings

The following strict checks are enabled:

| Setting | Purpose |
|---------|---------|
| `strict_equality` | Requires compatible types for `==` comparisons |
| `check_untyped_defs` | Type-checks function bodies even without annotations |
| `disallow_any_generics` | Requires type parameters for generics |
| `disallow_untyped_defs` | Requires type annotations on all functions |
| `disallow_untyped_calls` | Disallows calling untyped functions |
| `disallow_subclassing_any` | Prevents subclassing `Any` |

**Sources:** [pyproject.toml:215-235]()

### Excluded Files and Reasons

Mypy excludes specific files where its type inference is less effective or where it would be redundant:

```python
# From pyproject.toml:206-213
exclude = [
  'src/openai/_files.py',      # Mypy type narrowing issues
  '_dev/.*.py',                 # Development utilities
  'tests/.*',                   # Test inference issues
  'src/openai/_utils/_logs.py', # Internal logging utilities
  'examples/realtime/audio_util.py',
  'examples/realtime/push_to_talk_app.py',
]
```

**Sources:** [pyproject.toml:206-213]()

### Disabled Error Codes

Specific error codes are disabled to support the SDK's coding patterns:

```python
# From pyproject.toml:246
disable_error_code = "func-returns-value,overload-cannot-match"
```

**Sources:** [pyproject.toml:246]()

## Development Workflow Integration

### Script Commands

The `[tool.rye.scripts]` section defines command chains for quality checks:

Title: Development Command Workflow
```mermaid
graph LR
    subgraph "Format Chain"
        FORMAT["rye run format"]
        FORMAT_RUFF["format:ruff"]
        FORMAT_DOCS["format:docs"]
        FIX_RUFF["fix:ruff"]
        FORMAT_RUFF2["format:ruff (2nd pass)"]
    end
    
    FORMAT --> FORMAT_RUFF
    FORMAT_RUFF --> FORMAT_DOCS
    FORMAT_DOCS --> FIX_RUFF
    FIX_RUFF --> FORMAT_RUFF2
    
    subgraph "Lint Chain"
        LINT["rye run lint"]
        CHECK_RUFF["check:ruff"]
        TYPECHECK["typecheck"]
        CHECK_IMPORT["check:importable"]
    end
    
    LINT --> CHECK_RUFF
    CHECK_RUFF --> TYPECHECK
    TYPECHECK --> CHECK_IMPORT
```

**Sources:** [pyproject.toml:88-116]()

### Breaking Change Detection

The SDK includes a specialized script to detect breaking changes in the public API using `griffe`.

- **scripts/detect-breaking-changes.py**: Uses `griffe.load` and `griffe.load_git` to compare the current source with a previous git ref [scripts/detect-breaking-changes.py:56-64]().
- **find_breaking_changes**: A recursive function that identifies removed public members between two versions of the package [scripts/detect-breaking-changes.py:23-48]().
- **scripts/detect-breaking-changes**: A bash wrapper that checks out old test files and runs linting against them using a specialized pyright config to find incompatibilities [scripts/detect-breaking-changes:1-25]().

**Sources:** [scripts/detect-breaking-changes.py:1-80](), [scripts/detect-breaking-changes:1-25](), [scripts/pyrightconfig.breaking-changes.json:1-5]()

## Tool Version Management

### Pinned Versions

Development tool versions are pinned in `[tool.rye] dev-dependencies`:

| Tool | Version | Purpose |
|------|---------|---------|
| `pyright` | `==1.1.399` | Consistent type checking [pyproject.toml:65]() |
| `mypy` | `==1.17` | Secondary type checker [pyproject.toml:66]() |
| `ruff` | (managed) | Linter and formatter [pyproject.toml:71]() |
| `griffe` | `>=1` | Breaking change detection [pyproject.toml:85]() |

**Sources:** [pyproject.toml:61-86]()

---

# Page: CI/CD Pipeline and Release Process

# CI/CD Pipeline and Release Process

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.devcontainer/Dockerfile](.devcontainer/Dockerfile)
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [.github/workflows/create-releases.yml](.github/workflows/create-releases.yml)
- [.github/workflows/publish-pypi.yml](.github/workflows/publish-pypi.yml)
- [scripts/utils/upload-artifact.sh](scripts/utils/upload-artifact.sh)

</details>



This document describes the continuous integration and deployment infrastructure used by the OpenAI Python SDK. It covers the GitHub Actions workflows that run on every commit, the automated release process using `release-please`, and the PyPI publishing mechanism.

## Overview

The CI/CD pipeline is built entirely on GitHub Actions and consists of several core workflows:

- **CI Workflow** ([.github/workflows/ci.yml:1-204]()): Runs linting, building, testing (across multiple Python versions and HTTP clients), and example validation on every push and pull request.
- **Create Releases Workflow** ([.github/workflows/create-releases.yml:1-79]()): Triggers release automation and handles the publishing of tagged releases to PyPI.
- **Publish PyPI Workflow** ([.github/workflows/publish-pypi.yml:1-60]()): Manual workflow for re-running the publication process if automation fails.

The system uses `Rye 0.44.0` consistently across all environments for dependency management and build orchestration ([.github/workflows/ci.yml:34](), [.devcontainer/Dockerfile:6](), [.github/workflows/create-releases.yml:43]()).

## CI Pipeline Architecture

The CI pipeline ensures code quality and package integrity through a series of parallel jobs.

```mermaid
graph TB
    subgraph "Trigger Events"
        PUSH["Push to branches<br/>(main, codegen/stl/**, etc)"]
        PR["Pull Request"]
        SCHED["Schedule (Daily)"]
    end
    
    subgraph "CI Workflow (.github/workflows/ci.yml)"
        LINT["lint Job<br/>rye sync<br/>./scripts/lint"]
        BUILD["build Job<br/>rye build<br/>validate-python-version-wheel.py<br/>validate-bedrock-wheel.py"]
        TEST["test Job<br/>(Py 3.10, 3.14)<br/>./scripts/test"]
        TEST_HTTPX2["test-httpx2 Job<br/>(Py 3.14)<br/>OPENAI_TEST_HTTP_CLIENT=httpx2"]
        EXAMPLES["examples Job<br/>rye run python<br/>examples/demo.py"]
    end

    subgraph "Data Entities"
        WHL["dist/*.whl<br/>Wheel Artifact"]
        TAR["dist/*.tar.gz<br/>Source Dist"]
    end
    
    subgraph "External Systems"
        STAINLESS["Stainless Storage<br/>(Artifact Upload)"]
        PYPI["PyPI Registry<br/>(Release Only)"]
    end
    
    PUSH --> LINT
    PUSH --> BUILD
    PUSH --> TEST
    PUSH --> TEST_HTTPX2
    PUSH --> EXAMPLES
    
    PR --> LINT
    PR --> BUILD
    PR --> TEST
    
    SCHED --> TEST
    
    BUILD --> WHL
    WHL --> STAINLESS
    BUILD --> PYPI
```

**Sources:** [.github/workflows/ci.yml:1-204]()

### Workflow Triggers

The CI workflow ([.github/workflows/ci.yml:2-20]()) triggers on:

- **Push events**: All branches except specific preview branches like `stl-preview-head/**`, `generated`, and `codegen/**` (except `codegen/stl/**`).
- **Pull request events**: All pull requests except those targeting preview branches.
- **Scheduled events**: Daily at 09:47 UTC to test against the matrix and next CPython prereleases ([.github/workflows/ci.yml:20]()).

Each job includes conditional checks ([.github/workflows/ci.yml:27](), [44](), [114]()) to ensure jobs run for pushes to the main repository or pull requests from forks, while avoiding redundant runs for internal metadata commits.

**Sources:** [.github/workflows/ci.yml:2-114]()

## Continuous Integration Jobs

### Lint Job

The lint job ([.github/workflows/ci.yml:23-42]()) validates code quality using the `rye` environment. It executes `./scripts/lint`, which triggers the chain including `ruff` for linting/formatting and `mypy`/`pyright` for type checking.

### Build Job and Artifact Management

The build job ([.github/workflows/ci.yml:43-109]()) creates distributable packages and validates them against different Python environments.

1.  **Build**: Executes `rye build` ([.github/workflows/ci.yml:64]()).
2.  **Wheel Validation**: 
    - Runs `scripts/utils/validate-python-version-wheel.py` to check Python version metadata ([.github/workflows/ci.yml:67]()).
    - Runs `scripts/utils/validate-bedrock-wheel.py` for Bedrock-specific packaging ([.github/workflows/ci.yml:70]()).
    - Runs `scripts/utils/validate-httpx2-wheel.py` on Python 3.10 and 3.14 ([.github/workflows/ci.yml:73](), [89]()).
    - Verifies that Python 3.9 correctly rejects the wheel as it is no longer supported ([.github/workflows/ci.yml:81]()).
3.  **Stainless Upload**: For internal repository pushes, it uses `scripts/utils/upload-artifact.sh` to upload the wheel to Stainless storage ([.github/workflows/ci.yml:108]()). This script uses a GitHub OIDC token to authenticate and obtain a signed URL for the upload ([scripts/utils/upload-artifact.sh:6-19]()).

**Sources:** [.github/workflows/ci.yml:43-109](), [scripts/utils/upload-artifact.sh:1-28]()

### Test Jobs

The CI suite runs tests across a matrix of Python versions and HTTP client configurations:

- **Standard Tests**: Runs on Python 3.10 and 3.14 ([.github/workflows/ci.yml:119]()). It uses `./scripts/bootstrap` to prepare the environment and `./scripts/test` to execute the suite ([.github/workflows/ci.yml:141-144]()).
- **HTTPX2 Tests**: A specialized job ([.github/workflows/ci.yml:146-181]()) runs tests on Python 3.14 with both the standard `httpx` client and the `httpx2` client by setting the `OPENAI_TEST_HTTP_CLIENT` environment variable ([.github/workflows/ci.yml:174](), [179]()).

**Sources:** [.github/workflows/ci.yml:110-181]()

## Release Automation and Publishing

The SDK uses `release-please` to automate versioning and changelog generation.

```mermaid
sequenceDiagram
    participant GH as GitHub Push (main)
    participant RP as Release Please Action
    participant Build as Build Job
    participant Publish as Publish Job
    participant PyPI as PyPI Registry

    GH->>RP: Trigger Create Releases
    RP->>RP: Update CHANGELOG.md
    RP->>RP: Update _version.py
    RP-->>GH: Create Release PR / Tag Release
    
    Note over GH, RP: When Release PR is merged/tagged
    
    RP->>Build: releases_created == true
    Build->>Build: rye build --clean
    Build->>GH: Upload Artifact (dist/)
    
    GH->>Publish: Download Artifact
    Publish->>PyPI: pypa/gh-action-pypi-publish
```

### Automated Release Workflow

The `Create releases` workflow ([.github/workflows/create-releases.yml:1-79]()) manages the lifecycle:

1.  **Release Trigger**: The `stainless-api/trigger-release-please` action handles versioning based on conventional commits ([.github/workflows/create-releases.yml:21-25]()).
2.  **Build Step**: If a release is created, the `build` job runs `rye build --clean` ([.github/workflows/create-releases.yml:49]()) and uploads the resulting `dist/` folder as a GitHub Action artifact ([.github/workflows/create-releases.yml:52-57]()). This job explicitly lacks OIDC access for security ([.github/workflows/create-releases.yml:32-33]()).
3.  **Publish Step**: The `publish` job downloads the artifact and uses `pypa/gh-action-pypi-publish` to push the package to PyPI using Trusted Publishing (OIDC) via `id-token: write` ([.github/workflows/create-releases.yml:68-78]()).

**Sources:** [.github/workflows/create-releases.yml:1-79]()

## Manual Publishing

In cases where the automated workflow fails, the `Publish PyPI` workflow ([.github/workflows/publish-pypi.yml:1-60]()) can be triggered manually via `workflow_dispatch` ([.github/workflows/publish-pypi.yml:5]()). It follows the same build-then-publish pattern to ensure that the environment that builds the code is separate from the environment that holds the OIDC identity for PyPI ([.github/workflows/publish-pypi.yml:12-16]()).

**Sources:** [.github/workflows/publish-pypi.yml:1-60]()

## Development Environment Support

### Dev Container

The project includes a VS Code Dev Container configuration ([.devcontainer/devcontainer.json:1-43]()) to provide a consistent environment.
- **Dockerfile**: Base image is `python:3.9`, with `Rye 0.44.0` installed into the `vscode` user's path ([.devcontainer/Dockerfile:1-7]()).
- **Post-Start**: Automatically runs `rye sync --all-features` to ensure all optional dependencies are available ([.devcontainer/devcontainer.json:10]()).
- **VS Code Settings**: Configures the Python extension to use the `.venv/bin/python` interpreter created by Rye ([.devcontainer/devcontainer.json:19-20]()).

**Sources:** [.devcontainer/Dockerfile:1-10](), [.devcontainer/devcontainer.json:1-43]()

---

# Page: Glossary

# Glossary

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.release-please-manifest.json](.release-please-manifest.json)
- [.stats.yml](.stats.yml)
- [CHANGELOG.md](CHANGELOG.md)
- [README.md](README.md)
- [api.md](api.md)
- [pyproject.toml](pyproject.toml)
- [src/openai/__init__.py](src/openai/__init__.py)
- [src/openai/_base_client.py](src/openai/_base_client.py)
- [src/openai/_client.py](src/openai/_client.py)
- [src/openai/_compat.py](src/openai/_compat.py)
- [src/openai/_models.py](src/openai/_models.py)
- [src/openai/_types.py](src/openai/_types.py)
- [src/openai/_utils/__init__.py](src/openai/_utils/__init__.py)
- [src/openai/_utils/_json.py](src/openai/_utils/_json.py)
- [src/openai/_utils/_reflection.py](src/openai/_utils/_reflection.py)
- [src/openai/_utils/_sync.py](src/openai/_utils/_sync.py)
- [src/openai/_utils/_transform.py](src/openai/_utils/_transform.py)
- [src/openai/_utils/_typing.py](src/openai/_utils/_typing.py)
- [src/openai/_utils/_utils.py](src/openai/_utils/_utils.py)
- [src/openai/_version.py](src/openai/_version.py)
- [src/openai/lib/azure.py](src/openai/lib/azure.py)
- [src/openai/resources/beta/realtime/realtime.py](src/openai/resources/beta/realtime/realtime.py)
- [src/openai/resources/chat/completions/completions.py](src/openai/resources/chat/completions/completions.py)
- [src/openai/resources/realtime/realtime.py](src/openai/resources/realtime/realtime.py)
- [src/openai/resources/responses/responses.py](src/openai/resources/responses/responses.py)
- [src/openai/types/__init__.py](src/openai/types/__init__.py)
- [src/openai/types/chat/completion_create_params.py](src/openai/types/chat/completion_create_params.py)
- [src/openai/types/responses/response.py](src/openai/types/responses/response.py)
- [src/openai/types/responses/response_compact_params.py](src/openai/types/responses/response_compact_params.py)
- [src/openai/types/responses/response_create_params.py](src/openai/types/responses/response_create_params.py)
- [src/openai/types/responses/responses_client_event.py](src/openai/types/responses/responses_client_event.py)
- [src/openai/types/responses/responses_client_event_param.py](src/openai/types/responses/responses_client_event_param.py)
- [src/openai/types/shared/__init__.py](src/openai/types/shared/__init__.py)
- [src/openai/types/shared_params/__init__.py](src/openai/types/shared_params/__init__.py)
- [tests/api_resources/chat/test_completions.py](tests/api_resources/chat/test_completions.py)
- [tests/api_resources/test_responses.py](tests/api_resources/test_responses.py)
- [tests/lib/test_azure.py](tests/lib/test_azure.py)
- [tests/test_client.py](tests/test_client.py)
- [tests/test_models.py](tests/test_models.py)
- [tests/test_transform.py](tests/test_transform.py)
- [tests/test_utils/test_json.py](tests/test_utils/test_json.py)
- [tests/test_utils/test_logging.py](tests/test_utils/test_logging.py)
- [tests/test_utils/test_typing.py](tests/test_utils/test_typing.py)
- [tests/utils.py](tests/utils.py)

</details>



This glossary defines codebase-specific terms, architectural patterns, and domain concepts used within the OpenAI Python SDK. It serves as a reference for onboarding engineers to understand the mapping between API concepts and their internal implementations.

## Core Client Concepts

### BaseClient
The foundational abstract class for all SDK clients. It encapsulates the logic for HTTP communication, retry mechanisms, and request lifecycle management. It has two primary concrete implementations: `SyncAPIClient` and `AsyncAPIClient` [src/openai/_base_client.py:40-41](). It abstracts the underlying `httpx` client behavior [src/openai/_base_client.py:12-13]().

### FinalRequestOptions
An internal container used to store the fully processed state of a request (headers, query params, body, files) before it is handed off to the underlying HTTP transport (`httpx`) [src/openai/_models.py:33](), [src/openai/_base_client.py:76]().

### NotGiven / Omit
Sentinel values used to distinguish between a parameter being explicitly set to `None` (which may be meaningful to the API) and a parameter being entirely absent from the request [src/openai/_types.py:47-51](), [src/openai/_base_client.py:62-63]().

**Diagram: Request Option Construction**

```mermaid
graph TD
    subgraph "Natural Language Space"
        UserCall["User calls client.responses.create(model='...', stream=True)"]
    end

    subgraph "Code Entity Space"
        Resource["SyncAPIResource (e.g., Responses)"]
        MakeOptions["make_request_options()"]
        FinalOptions["FinalRequestOptions"]
        BaseClient["BaseClient._request()"]
    end

    UserCall --> Resource
    Resource --> MakeOptions
    MakeOptions --> FinalOptions
    FinalOptions --> BaseClient
```
Sources: [src/openai/_base_client.py:58-76](), [src/openai/resources/responses/responses.py:133-166](), [tests/test_client.py:38-39]()

---

## Data Modeling and Transformation

### BaseModel / GenericModel
A customized wrapper around Pydantic's `BaseModel`. It provides compatibility between Pydantic v1 and v2 via a compatibility shim [src/openai/_compat.py:65-73](), along with helper methods like `to_dict()` and `to_json()` that respect API aliases [src/openai/_models.py:111-212]().

### PropertyInfo
A metadata class used within `Annotated` types to provide instructions to the transformation pipeline. It handles field aliasing (mapping Python snake_case to API camelCase) and specific formatting requirements [src/openai/_models.py:55](), [src/openai/_utils/_transform.py]().

### construct_type
A core utility function used to instantiate complex types (unions, lists of models) from raw API response dictionaries. It performs loose type coercion to ensure robustness against API changes [src/openai/_base_client.py:76](), [src/openai/_models.py:36]().

**Diagram: Data Flow - Response Parsing**

```mermaid
graph TD
    subgraph "Network"
        RawJSON["Raw JSON Response Body"]
    end

    subgraph "Code Entity Space"
        APIResponse["APIResponse Class"]
        ParseMethod["APIResponse.parse()"]
        ConstructType["construct_type()"]
        PydanticModel["BaseModel Instance"]
    end

    RawJSON --> APIResponse
    APIResponse --> ParseMethod
    ParseMethod --> ConstructType
    ConstructType --> PydanticModel
```
Sources: [src/openai/_base_client.py:76-82](), [src/openai/_response.py:78-82](), [src/openai/_models.py:111-130]()

---

## Authentication Patterns

### Workload Identity
A secure authentication mechanism for automated environments (Kubernetes, Azure, GCP). It replaces long-lived API keys with short-lived tokens provided by an identity provider [src/openai/_client.py:13-14](), [src/openai/_client.py:110-114]().

### Admin API Key
A specialized credential used for organization-level management tasks, typically passed via environment variables like `OPENAI_ADMIN_KEY` [src/openai/_client.py:130-131](), [src/openai/_client.py:161-162]().

---

## Technical Abbreviations & Jargon

| Term | Definition | Code Pointer |
| :--- | :--- | :--- |
| **SSE** | Server-Sent Events. Used for streaming responses in Chat and Responses API. | [src/openai/_base_client.py:92]() |
| **CastTo** | An internal type hint or class passed to request methods to define the expected return type. | [src/openai/_base_client.py:52]() |
| **HttpxSendArgs** | Dictionary of arguments compatible with `httpx.Client.send()`. | [src/openai/_types.py:57]() |
| **BinaryTypes** | Union of types acceptable for file uploads (bytes, file-like objects, etc.). | [src/openai/_types.py:55]() |
| **SensitiveHeadersFilter** | A logging filter that prevents API keys and other secrets from appearing in trace logs. | [src/openai/_base_client.py:104]() |
| **Jiter** | A high-performance JSON parser used as a dependency for speed. | [pyproject.toml:19]() |

---

## Tooling and Infrastructure

### Rye
The primary project manager used for dependency management, virtual environment handling, and script execution [pyproject.toml:61-63]().

### Stainless
The code generation platform used to produce this SDK from the OpenAI OpenAPI specification [README.md:10-11]().

### Release-Please
An automated tool that manages the `CHANGELOG.md` and bumps versions in `_version.py` based on conventional commit messages [src/openai/_version.py:4](), [.release-please-manifest.json:1-3]().

Sources: [pyproject.toml:1-110](), [src/openai/_base_client.py:1-230](), [src/openai/_models.py:1-213](), [src/openai/_client.py:1-185](), [src/openai/resources/responses/responses.py:1-130]()