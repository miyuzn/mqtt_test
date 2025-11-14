package com.budiyev.android.codescanner;

import android.content.Context;
import androidx.annotation.Nullable;

public class CodeScanner {

    private DecodeCallback decodeCallback;

    public CodeScanner(Context context, @Nullable Object previewView) {
        // Stub constructor for compatibility only.
    }

    public void setDecodeCallback(DecodeCallback callback) {
        this.decodeCallback = callback;
    }

    public DecodeCallback getDecodeCallback() {
        return decodeCallback;
    }

    public void releaseResources() {
        // No-op stub.
    }
}
