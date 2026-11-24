function wechatArticleUrl(value) {
  const url = typeof value === 'string' ? value.trim() : '';
  if (url.length > 4096 || !/^https:\/\/mp\.weixin\.qq\.com\/s(?:\/[A-Za-z0-9_-]+)?(?:\?[^\s<>"']+)?(?:#[^\s<>"']*)?$/.test(url)) {
    return '';
  }
  return url;
}

module.exports = { wechatArticleUrl };
