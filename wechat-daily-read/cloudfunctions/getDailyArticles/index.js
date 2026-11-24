const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();

exports.main = async (event = {}) => {
  const { OPENID: owner } = cloud.getWXContext();
  if (!owner || typeof event.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(event.date)) {
    return { success: false, error: '缺少有效的用户或日期' };
  }
  try {
    const { data: accountRows } = await db.collection('accounts')
      .where({ owner, isActive: true }).limit(100).get();
    const enabled = new Set(accountRows.map(row => row.biz));
    const { data } = await db.collection('articles').where({ owner, date: event.date })
      .orderBy('publishTime', 'desc').limit(100).get();
    const articles = data.filter(row => enabled.has(row.accountBiz)).map(row => ({
      id: row._id,
      title: row.title,
      accountName: row.accountName,
      accountBiz: row.accountBiz,
      category: row.category || '其他',
      digest: row.digest || '',
      content: row.content || '',
      thumbUrl: row.thumbUrl || '',
      url: row.url || '',
      publishTime: row.publishTime,
      readCount: Number(row.readCount) || 0,
      hasRead: false,
    }));
    const summary = articles.length ? `已收录 ${articles.length} 篇文章` : '该日暂无已导入的文章';
    return { success: true, articles, summary, total: articles.length };
  } catch {
    return { success: false, error: '无法读取云端文章，请检查云数据库和索引配置' };
  }
};
