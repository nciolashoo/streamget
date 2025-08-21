import json
import re
import urllib.parse

from ...data import StreamData, wrap_stream
from ...requests.async_http import async_req
from ..base import BaseLiveStream


class JDLiveStream(BaseLiveStream):
    """
    A class for fetching and processing JD live stream information.
    """
    def __init__(self, proxy_addr: str | None = None, cookies: str | None = None):
        super().__init__(proxy_addr, cookies)
        self.mobile_headers = self._get_mobile_headers()

    def _get_mobile_headers(self) -> dict:
        return {
            'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
            'origin': 'https://lives.jd.com',
            'referer': 'https://lives.jd.com/',
            'x-referer-page': 'https://lives.jd.com/',
            'cookie': self.cookies or '',
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
        result = {"anchor_name": '', "is_live": False}
        
        url = await async_req(url, proxy_addr=self.proxy_addr, headers=self.mobile_headers, redirect_url=True)
        #尝试直接在链接里获取参数authorId         
        author_id=self.get_params(url,'authorId')
        if not author_id:
            #没能通过链接获取参数authorId的情况下，尝试直接在链接里获取参数liveId
            live_id = self.get_params(url, 'liveId')
            if not live_id:
                #没能通过链接获取参数authorId或liveId的情况下，通过正则匹配寻找liveId
                live_id_matchs = re.search('#/(.*?)\\?origin', url)
                if live_id_matchs:
                    live_id = live_id_matchs.group(1)
            
            if not live_id:
                #尝试所有途径获取liveId失败，无法通过liveId获取authorId，抛出异常
                raise Exception('Error: Invalid URL: missing required parameters "authorId" or "liveId"')
            
            params = {
                'functionId': 'liveBasicDetailToM',
                'appid': 'live_pc',
                'body': '{"liveId":"' + live_id + '"}'
            }
            info_api = f'https://api.m.jd.com/api?{urllib.parse.urlencode(params)}'
            json_str = await async_req(info_api,proxy_addr=self.proxy_addr, headers=self.mobile_headers)
            json_data = json.loads(json_str)
            if 'data' in json_data and 'authorInfo' in json_data['data']:
                author_id=json_data['data']['authorInfo']['authorId']
                
            if not author_id:
                #尝试所有途径获取authorId失败，抛出异常
                raise Exception('Error: The live room URL has expired. Please use the URL of the currently active live stream.')
                                
        result['fixed_url']=f"https://eco.m.jd.com/content/dr_home/index.html?authorId={author_id}"
        data = {
                'functionId': 'talent_head_findTalentMsg',
                'appid': 'dr_detail',
                'body': '{"authorId":"' + author_id + '","monitorSource":"1","userId":""}',
            }
        info_api = 'https://api.m.jd.com/talent_head_findTalentMsg'
        json_str = await async_req(info_api, data=data, proxy_addr=self.proxy_addr, headers=self.mobile_headers)
        json_data = json.loads(json_str)
        anchor_name = json_data['result']['talentName']
        result['anchor_name'] = anchor_name
        if 'livingRoomJump' not in json_data['result']:
            return result
        #通过authorId获取当前live_id
        live_id = json_data['result']['livingRoomJump']['params']['id']
        
                
        params = {
            "body": '{"liveId": "' + live_id + '"}',
            "functionId": "getImmediatePlayToM",
            "appid": "h5-live"
        }

        api = f'https://api.m.jd.com/client.action?{urllib.parse.urlencode(params)}'
        # backup_api: https://api.m.jd.com/api
        json_str = await async_req(api, proxy_addr=self.proxy_addr, headers=self.mobile_headers)
        json_data = json.loads(json_str)
        live_status = json_data['data']['status']
        if live_status == 1:
            flv_url = json_data['data']['videoUrl']
            m3u8_url = json_data['data']['h5VideoUrl']
            result |= {"is_live": True, "m3u8_url": m3u8_url, "flv_url": flv_url, "record_url": flv_url}
        return result

    @staticmethod
    async def fetch_stream_url(json_data: dict, video_quality: str | int | None = None) -> StreamData:
        """
        Fetches the stream URL for a live room and wraps it into a StreamData object.
        """
        json_data |= {"platform": "京东直播"}
        json_data['extra']={'fixed_url':json_data.pop('fixed_url',None)}
        return wrap_stream(json_data)
