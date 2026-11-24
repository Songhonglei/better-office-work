exports.main = async (event = {}) => {
  if (!Array.isArray(event.articles) || event.articles.length === 0) {
    return { success: false, error: '没有可汇总的文章' };
  }
  const groups = new Map();
  for (const article of event.articles.slice(0, 100)) {
    if (!article || typeof article.title !== 'string') continue;
    const category = typeof article.category === 'string' ? article.category.slice(0, 20) : '其他';
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(article.title.slice(0, 120));
  }
  if (!groups.size) return { success: false, error: '没有可汇总的文章' };
  const lines = [];
  for (const [category, titles] of groups) {
    lines.push(`【${category}】${titles.length} 篇`, ...titles.slice(0, 3).map(title => `• ${title}`));
  }
  return { success: true, summary: lines.join('\n') };
};
