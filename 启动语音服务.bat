@echo off
chcp 65001 >nul
title GPT-SoVITS 语音服务 (许墨)
cd /d D:\GPT-SoVITS-v2pro-20250604-nvidia50
echo 正在加载许墨语音模型（首次启动需要 1-2 分钟）...
echo   GPT   权重: GPT_weights_v2Pro\xumo-e20.ckpt
echo   SoVITS 权重: SoVITS_weights_v2Pro\xumo_e12_s300.pth
echo 模型加载完成后请保持本窗口开启，关闭窗口语音服务即停止。
runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS\configs\tts_infer.yaml
pause
