// Reserved cloud function name so older clients receive an actionable response.
exports.main = async () => ({ success: false, error: '当前版本尚未配置语音服务' });
