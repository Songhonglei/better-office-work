const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const accounts = cloud.database().collection('accounts');

function parseArticle(value) {
  const url = new URL(value);
  if (url.origin !== 'https://mp.weixin.qq.com' || url.username || url.password ||
      !/^\/s(?:\/[A-Za-z0-9_-]+)?$/.test(url.pathname)) {
    throw new Error('请输入微信公众号文章链接');
  }
  const biz = url.searchParams.get('__biz') || '';
  if (!/^[A-Za-z0-9_+=/-]{1,128}$/.test(biz)) {
    throw new Error('该短链接未提供公众号 ID，可在账号管理中手动添加');
  }
  return { biz, name: '公众号_' + biz.slice(-6), sourceUrl: url.origin + url.pathname };
}

exports.main = async (event = {}) => {
  const { OPENID: owner } = cloud.getWXContext();
  if (!owner) return { success: false, error: '无法识别当前用户' };
  const action = event.action || 'detect';
  try {
    if (action === 'list') {
      const { data } = await accounts.where({ owner }).limit(100).get();
      return { success: true, data };
    }
    if (action === 'toggle' || action === 'delete') {
      if (typeof event.id !== 'string' || !event.id || (action === 'toggle' && typeof event.isActive !== 'boolean')) {
        return { success: false, error: '账号参数无效' };
      }
      const owned = accounts.where({ owner, _id: event.id });
      const { stats } = action === 'delete'
        ? await owned.remove()
        : await owned.update({ data: { isActive: event.isActive } });
      return stats && (stats.updated || stats.removed)
        ? { success: true }
        : { success: false, error: '找不到可操作的账号' };
    }
    if (action !== 'detect' && action !== 'add') {
      return { success: false, error: '不支持的账号操作' };
    }

    const supplied = action === 'detect' ? parseArticle(event.url) : event;
    const biz = typeof supplied.biz === 'string' ? supplied.biz.trim() : '';
    const name = typeof supplied.name === 'string' ? supplied.name.trim() : '';
    if (!/^[A-Za-z0-9_+=/-]{1,128}$/.test(biz) || !name || name.length > 80) {
      return { success: false, error: '请填写有效的公众号名称和 ID' };
    }
    const result = await accounts.where({ owner, biz }).limit(1).get();
    if (result.data.length) {
      return { success: true, account: result.data[0], isNew: false };
    }
    const record = {
      owner, biz, name, isActive: true, createTime: new Date(),
      category: typeof supplied.category === 'string' ? supplied.category.slice(0, 20) : '其他',
      sourceUrl: action === 'detect' ? supplied.sourceUrl : '',
    };
    const { _id } = await accounts.add({ data: record });
    return { success: true, account: { ...record, _id }, isNew: true };
  } catch (error) {
    return {
      success: false,
      error: action === 'detect' && /公众号|链接/.test(error.message) ? error.message : '公众号操作失败，请检查云数据库配置',
    };
  }
};
