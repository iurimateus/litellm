import json
from typing import Any, Dict, Optional

import litellm
from litellm import verbose_logger
from litellm.types.llms.openai import (
    ChatCompletionToolCallChunk,
    ChatCompletionToolCallFunctionChunk,
    ChatCompletionUsageBlock,
)
from litellm.types.utils import GenericStreamingChunk, Usage


class ModelResponseIterator:
    def __init__(self, streaming_response, sync_stream: bool):
        self.streaming_response = streaming_response

    def chunk_parser(self, chunk: dict) -> GenericStreamingChunk:
        try:
            processed_chunk = litellm.ModelResponseStream(**chunk)

            text = ""
            tool_use: Optional[ChatCompletionToolCallChunk] = None
            is_finished = False
            finish_reason = ""
            usage: Optional[ChatCompletionUsageBlock] = None
            provider_specific_fields: Optional[Dict[str, Any]] = None

            if processed_chunk.choices[0].delta.content is not None:  # type: ignore
                text = processed_chunk.choices[0].delta.content  # type: ignore

            if 'reasoning_content' in processed_chunk.choices[0].delta and processed_chunk.choices[0].delta.reasoning_content is not None:  # type: ignore
                provider_specific_fields = {
                    'reasoning_content': processed_chunk.choices[0].delta.reasoning_content # type: ignore
                }
            
            if (
                processed_chunk.choices[0].delta.tool_calls is not None  # type: ignore
                and len(processed_chunk.choices[0].delta.tool_calls) > 0  # type: ignore
                and processed_chunk.choices[0].delta.tool_calls[0].function is not None  # type: ignore
                and processed_chunk.choices[0].delta.tool_calls[0].function.arguments  # type: ignore
                is not None
            ):
                tool_use = ChatCompletionToolCallChunk(
                    id=processed_chunk.choices[0].delta.tool_calls[0].id,  # type: ignore
                    type="function",
                    function=ChatCompletionToolCallFunctionChunk(
                        name=processed_chunk.choices[0]
                        .delta.tool_calls[0]  # type: ignore
                        .function.name,
                        arguments=processed_chunk.choices[0]
                        .delta.tool_calls[0]  # type: ignore
                        .function.arguments,
                    ),
                    index=processed_chunk.choices[0].delta.tool_calls[0].index,
                )

            if processed_chunk.choices[0].finish_reason is not None:
                is_finished = True
                finish_reason = processed_chunk.choices[0].finish_reason

            usage_chunk: Optional[Usage] = getattr(processed_chunk, "usage", None)
            if usage_chunk is not None:
                usage = ChatCompletionUsageBlock(
                    prompt_tokens=usage_chunk.prompt_tokens,
                    completion_tokens=usage_chunk.completion_tokens,
                    total_tokens=usage_chunk.total_tokens,
                )

            if not provider_specific_fields:
                provider_specific_fields = getattr(processed_chunk.choices[0].delta, "provider_specific_fields", None)

            if error := chunk.get("error", None):
                # hack for openrouter errors
                # {
                #   'message': 'Rate limit exceeded: free-models-per-day',
                #   'code': 429,
                #   'metadata': {'headers': {'X-RateLimit-Limit': '200', 'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1741132800000'}}
                # }
                print(f"streaming_utils.py:70: error={error}")
                raise Exception(error)

            return GenericStreamingChunk(
                text=text,
                tool_use=tool_use,
                is_finished=is_finished,
                finish_reason=finish_reason,
                usage=usage,
                index=0,
                provider_specific_fields=provider_specific_fields,
            )
        except json.JSONDecodeError:
            raise ValueError(f"Failed to decode JSON from chunk: {chunk}")

    # Sync iterator
    def __iter__(self):
        self.response_iterator = self.streaming_response
        return self

    def __next__(self):
        if not hasattr(self, "response_iterator"):
            self.response_iterator = self.streaming_response
        try:
            chunk = self.response_iterator.__next__()
        except StopIteration:
            raise StopIteration
        except ValueError as e:
            raise RuntimeError(f"Error receiving chunk from stream: {e}")

        try:
            chunk = chunk.replace("data:", "")
            chunk = chunk.strip()
            if len(chunk) > 0:
                json_chunk = json.loads(chunk)
                return self.chunk_parser(chunk=json_chunk)
            else:
                return GenericStreamingChunk(
                    text="",
                    is_finished=False,
                    finish_reason="",
                    usage=None,
                    index=0,
                    tool_use=None,
                )
        except StopIteration:
            raise StopIteration
        except ValueError as e:
            verbose_logger.debug(
                f"Error parsing chunk: {e},\nReceived chunk: {chunk}. Defaulting to empty chunk here."
            )
            return GenericStreamingChunk(
                text="",
                is_finished=False,
                finish_reason="",
                usage=None,
                index=0,
                tool_use=None,
            )

    # Async iterator
    def __aiter__(self):
        self.async_response_iterator = self.streaming_response.__aiter__()
        return self

    async def __anext__(self):
        try:
            chunk = await self.async_response_iterator.__anext__()
        except StopAsyncIteration:
            raise StopAsyncIteration
        except ValueError as e:
            raise RuntimeError(f"Error receiving chunk from stream: {e}")
        except Exception as e:
            raise RuntimeError(f"Error receiving chunk from stream: {e}")

        try:
            chunk = chunk.replace("data:", "")
            chunk = chunk.strip()
            if chunk == "[DONE]":
                raise StopAsyncIteration
            if len(chunk) > 0:
                json_chunk = json.loads(chunk)
                return self.chunk_parser(chunk=json_chunk)
            else:
                return GenericStreamingChunk(
                    text="",
                    is_finished=False,
                    finish_reason="",
                    usage=None,
                    index=0,
                    tool_use=None,
                )
        except StopAsyncIteration:
            raise StopAsyncIteration
        except ValueError as e:
            verbose_logger.debug(
                f"Error parsing chunk: {e},\nReceived chunk: {chunk}. Defaulting to empty chunk here."
            )
            return GenericStreamingChunk(
                text="",
                is_finished=False,
                finish_reason="",
                usage=None,
                index=0,
                tool_use=None,
            )
