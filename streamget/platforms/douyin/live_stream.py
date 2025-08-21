import json
import re
import urllib.parse

from ...data import StreamData, wrap_stream
from ...requests.async_http import async_req, get_response_status
from ..base import BaseLiveStream


class DouyinLiveStream(BaseLiveStream):
    """
    A class for fetching and processing Douyin live stream information.
    """
    def __init__(self, proxy_addr: str | None = None, cookies: str | None = None):
        super().__init__(proxy_addr, cookies)
        self.mobile_headers = self._get_mobile_headers()
        self.pc_headers = self._get_pc_headers()

    def _get_pc_headers(self) -> dict:
        return {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'accept-language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'cookie': self.cookies or '__ac_nonce=064caded4009deafd8b89;',
            'referer': 'https://live.douyin.com/'
        }


    async def fetch_web_stream_data(self, url: str, process_data: bool = True) -> dict:
        """
        Fetches web stream data for a live room.

        Args:
            url (str): The room URL.
            process_data (bool): Whether to process the data. Defaults to True.

        Returns:
            dict: A dictionary containing anchor name, live status, room URL, and title.
        """
        try:
            if 'douyin.com/follow/live/' in url:
                #https://www.douyin.com/follow/live/71967971105
                url=await async_req(url, proxy_addr=self.proxy_addr, headers=self.pc_headers, redirect_url=True)
            elif 'v.douyin.com/' in url or 'douyin.com/user/' in url:
                if 'v.douyin.com' in url:
                    url = await async_req(url, proxy_addr=self.proxy_addr, headers=self.pc_headers, redirect_url=True)
                    parsed_url = urllib.parse.urlparse(url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    if 'sec_uid' in query_params:
                        sec_uid = query_params['sec_uid'][0]
                    elif 'sec_user_id' in query_params:
                        sec_uid = query_params['sec_user_id'][0]
                    else:
                        raise Exception("Could not find sec_user_id  or sec_uid in the redirect URL")
                else:
                    #https://www.douyin.com/user/MS4wLjABAAAAfJdQBvOV3r8BEC7SSnDGmkUIJ_I3mggDO2TeeRUmBSqRVRjhTdzkiGtEIqyLLONV
                    sec_uid = url.split('?')[0].rsplit('douyin.com/user/', maxsplit=1)[-1] 
                #把 sec_uid 转换成数字 uid
                api_url = f"https://www.iesdouyin.com/web/api/v2/user/info?sec_uid={sec_uid}"
                json_str = await async_req(api_url,proxy_addr=self.proxy_addr, headers=self.pc_headers)
                json_data=json.loads(json_str)
                if 'user_info' in json_data and 'unique_id' in json_data['user_info']:
                    unique_id=str(json_data["user_info"]["unique_id"])
                else:
                    raise Exception(f"Could not get unique_id from {api_url}")
                url=f"https://live.douyin.com/{unique_id}"
                
            if 'live.douyin.com/' not in url:
                raise Exception(f'Error: Invalid douyin live room URL {url}')
            
            origin_url_list = None
            html_str = await async_req(url, proxy_addr=self.proxy_addr, headers=self.pc_headers)
            match_json_str = re.search(r'(\{\\"state\\":.*?)]\\n"]\)', html_str)
            if not match_json_str:
                match_json_str = re.search(r'(\{\\"common\\":.*?)]\\n"]\)</script><div hidden', html_str)
            json_str = match_json_str.group(1)
            cleaned_string = json_str.replace('\\', '').replace(r'u0026', r'&')
            room_store = re.search('"roomStore":(.*?),"linkmicStore"', cleaned_string, re.DOTALL).group(1)
            anchor_name = re.search('"nickname":"(.*?)","avatar_thumb', room_store, re.DOTALL).group(1)
            room_store = room_store.split(',"has_commerce_goods"')[0] + '}}}'
            if not process_data:
                return json.loads(room_store)
            else:
                json_data = json.loads(room_store)['roomInfo']['room']
                #返回修正过的直播间地址,方便下次直接用修正过的直播间地址，减少请求次数
                json_data['fixed_url']=url
                json_data['anchor_name'] = anchor_name
                if 'status' in json_data and json_data['status'] == 4:
                    return json_data
                stream_orientation = json_data['stream_url']['stream_orientation']
                match_json_str2 = re.findall(r'"(\{\\"common\\":.*?)"]\)</script><script nonce=', html_str)
                if match_json_str2:
                    json_str = match_json_str2[0] if stream_orientation == 1 else match_json_str2[1]
                    json_data2 = json.loads(
                        json_str.replace('\\', '').replace('"{', '{').replace('}"', '}').replace('u0026', '&'))
                    if 'origin' in json_data2['data']:
                        origin_url_list = json_data2['data']['origin']['main']

                else:
                    html_str = html_str.replace('\\', '').replace('u0026', '&')
                    match_json_str3 = re.search('"origin":\\{"main":(.*?),"dash"', html_str, re.DOTALL)
                    if match_json_str3:
                        origin_url_list = json.loads(match_json_str3.group(1) + '}')

                if origin_url_list:
                    origin_hls_codec = origin_url_list['sdk_params'].get('VCodec') or ''
                    origin_m3u8 = {'ORIGIN': origin_url_list["hls"] + '&codec=' + origin_hls_codec}
                    origin_flv = {'ORIGIN': origin_url_list["flv"] + '&codec=' + origin_hls_codec}
                    hls_pull_url_map = json_data['stream_url']['hls_pull_url_map']
                    flv_pull_url = json_data['stream_url']['flv_pull_url']
                    json_data['stream_url']['hls_pull_url_map'] = {**origin_m3u8, **hls_pull_url_map}
                    json_data['stream_url']['flv_pull_url'] = {**origin_flv, **flv_pull_url}
            return json_data

        except Exception as e:
            raise Exception(f"Fetch failed: {url}, {e}")

    async def fetch_stream_url(self, json_data: dict, video_quality: str | int | None = None) -> StreamData:
        """
        Fetches the stream URL for a live room and wraps it into a StreamData object.
        """
        anchor_name = json_data.get('anchor_name')
        result = {"platform": "抖音", "anchor_name": anchor_name, "is_live": False}
        status = json_data.get("status", 4)
        if status == 2:
            stream_url = json_data['stream_url']
            flv_url_dict = stream_url['flv_pull_url']
            flv_url_list: list = list(flv_url_dict.values())
            m3u8_url_dict = stream_url['hls_pull_url_map']
            m3u8_url_list: list = list(m3u8_url_dict.values())
            while len(flv_url_list) < 5:
                flv_url_list.append(flv_url_list[-1])
                m3u8_url_list.append(m3u8_url_list[-1])
            video_quality, quality_index = self.get_quality_index(video_quality)
            m3u8_url = m3u8_url_list[quality_index]
            flv_url = flv_url_list[quality_index]
            ok = await get_response_status(url=m3u8_url, proxy_addr=self.proxy_addr, headers=self.pc_headers)
            if not ok:
                index = quality_index+1 if quality_index < 4 else quality_index - 1
                m3u8_url = m3u8_url_list[index]
                flv_url = flv_url_list[index]

            result |= {
                'is_live': True,
                'title': json_data['title'],
                'quality': video_quality,
                'm3u8_url': m3u8_url,
                'flv_url': flv_url,
                'record_url': m3u8_url or flv_url,
            }
        if 'fixed_url' in json_data:
            #返回修正过的直播间地址,方便下次直接用修正过的直播间地址，减少请求次数
            result['extra']={'fixed_url':json_data['fixed_url']}
        return wrap_stream(result)
