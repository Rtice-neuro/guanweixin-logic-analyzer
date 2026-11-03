param([Parameter(Mandatory=$true)][ValidatePattern('^COM[0-9]+$')][string]$Port)
$ErrorActionPreference='Stop'
function Emit($value){[Console]::Out.WriteLine(($value|ConvertTo-Json -Compress));[Console]::Out.Flush()}
Add-Type -TypeDefinition @'
using System;
using System.Threading.Tasks;
public static class GwxCommandInput {
 public static Task<string> ReadAsync() {
  return Task.Run(() => Console.In.ReadLine());
 }
}
'@
$serial=[IO.Ports.SerialPort]::new($Port,115200,'None',8,'One')
$serial.DtrEnable=$false;$serial.RtsEnable=$false
try{
 $serial.Open();Emit @{event='connected';port=$Port}
 $inputTask=[GwxCommandInput]::ReadAsync()
 $presenceWatch=[Diagnostics.Stopwatch]::StartNew()
 while($true){
  if($presenceWatch.ElapsedMilliseconds -ge 1000){
   $presenceWatch.Restart()
   if(-not ([IO.Ports.SerialPort]::GetPortNames() -contains $Port)){
    throw "Serial device removed: $Port"
   }
  }
  if($inputTask.IsCompleted){
   $line=$inputTask.Result;if($null -eq $line){break}
   if($line -cmatch '^[0-9A-F]{32}$'){
    $bytes=New-Object byte[] 16;$xor=0
    for($i=0;$i -lt 16;$i++){$bytes[$i]=[Convert]::ToByte($line.Substring($i*2,2),16);$xor=$xor -bxor $bytes[$i]}
    if($xor -eq 0 -and $bytes[0] -eq 165 -and $bytes[1] -eq 90 -and $bytes[2] -eq 1){
     $serial.Write($bytes,0,16);Emit @{event='sent';packet=$line}
    }else{Emit @{event='error';message='Invalid command checksum/header'}}
   }else{Emit @{event='error';message='Invalid command length'}}
   $inputTask=[GwxCommandInput]::ReadAsync()
  }
  $available=$serial.BytesToRead
  if($available -gt 0){
   $buffer=New-Object byte[] ([Math]::Min($available,4096))
   $received=$serial.Read($buffer,0,$buffer.Length)
   if($received -gt 0){Emit @{event='rx';data=[Convert]::ToBase64String($buffer,0,$received)}}
  }
  else{Start-Sleep -Milliseconds 10}
 }
}catch{Emit @{event='error';message=$_.Exception.Message};exit 1}
finally{if($serial.IsOpen){$serial.Close()};$serial.Dispose()}
