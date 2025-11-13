package com.example.e_textilesendingserver.util

import java.util.concurrent.CompletableFuture
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

suspend fun <T> CompletableFuture<T>.await(): T =
    suspendCancellableCoroutine { cont ->
        whenComplete { result, throwable ->
            if (throwable != null) {
                cont.resumeWithException(throwable)
            } else {
                cont.resume(result)
            }
        }
        cont.invokeOnCancellation { cancel(true) }
    }
