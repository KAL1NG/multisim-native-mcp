"""Create, analyze and save a voltage divider through the installed MCP server."""
import asyncio,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client


async def create_divider(output: Path):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    parameters=StdioServerParameters(command=sys.executable,args=['-m','multisim_native_mcp'])
    async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=90) as session:
            await session.initialize()
            async def call(tool_name,**args):
                result=await session.call_tool(tool_name,args)
                if result.is_error:raise RuntimeError(result.content[0].text)
                return result.structured_content or json.loads(result.content[0].text)
            try:
                await call('native_create_circuit',title='Voltage divider')
                for name,ref,x,y in [('DC_POWER','V1',108,108),('RESISTOR_VIRTUAL','R1',306,108),('RESISTOR_VIRTUAL','R2',504,108),('GROUND','0',108,306)]:
                    await call('native_place_component',name=name,reference=ref,x=x,y=y)
                for ref,value in [('V1',12),('R1',1000),('R2',1000)]:
                    await call('native_set_parameter',component_ref=ref,index=1,value=value)
                for a,ap,b,bp in [('V1','1','R1','1'),('R1','2','R2','1'),('R2','2','V1','2'),('V1','2','0','1')]:
                    await call('native_connect_pins',source_ref=a,source_pin=ap,target_ref=b,target_pin=bp)
                netlist=await call('native_check_netlist')
                if netlist['failed']:raise RuntimeError(netlist['messages'])
                result=await call('native_run_analysis',analysis='op')
                await call('native_save_copy',output_path=str(output/'voltage-divider.ms14'),overwrite=True)
                await call('native_export_image',output_path=str(output/'voltage-divider.png'),overwrite=True)
                (output/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                return result
            finally:
                await call('native_close_copy')


if __name__=='__main__':
    print(json.dumps(asyncio.run(create_divider(Path(sys.argv[1] if len(sys.argv)>1 else 'output'))),indent=2))
