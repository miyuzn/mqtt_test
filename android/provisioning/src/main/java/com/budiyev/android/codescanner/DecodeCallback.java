package com.budiyev.android.codescanner;

import androidx.annotation.NonNull;
import com.google.zxing.Result;

public interface DecodeCallback {
    void onDecoded(@NonNull Result result);
}
