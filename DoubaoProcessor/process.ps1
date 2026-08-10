param(
    [string]$SourceFolder
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path


$Input="$Root\temp_input"
$WatermarkRemoved="$Root\temp_removed"
$Output="$Root\output"


$Exif="$Root\Tools\exiftool-13.59_64\exiftool.exe"
$ICC="$Root\Tools\sRGB-IEC61966-2.1.icc"


# 清理旧目录

Remove-Item $Input -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $WatermarkRemoved -Recurse -Force -ErrorAction SilentlyContinue


New-Item $Input -ItemType Directory
New-Item $WatermarkRemoved -ItemType Directory
New-Item $Output -ItemType Directory -Force



Write-Host ""
Write-Host "====== Step 1 去除水印 ======"
Write-Host ""


# 复制图片

Copy-Item "$SourceFolder\*" $Input



remove-ai-watermarks batch `
$Input `
-o $WatermarkRemoved `
--mode metadata



Write-Host ""
Write-Host "====== Step 2 手机化处理 ======"
Write-Host ""



# 手机型号库

$phones=@(
    @{
        Make="Apple"
        Model="iPhone 15"
        Lens="iPhone 15 back triple camera 24mm f/1.78"
    },
    @{
        Make="Apple"
        Model="iPhone 15 Pro"
        Lens="iPhone 15 Pro back triple camera 24mm f/1.78"
    },
    @{
        Make="Apple"
        Model="iPhone 16"
        Lens="iPhone 16 Main Camera"
    },
    @{
        Make="Apple"
        Model="iPhone 16 Plus"
        Lens="iPhone 16 Plus Main Camera"
    },
    @{
        Make="Apple"
        Model="iPhone 16 Pro"
        Lens="iPhone 16 Pro Main Camera"
    },
    @{
        Make="Apple"
        Model="iPhone 16 Pro Max"
        Lens="iPhone 16 Pro Max Main Camera"
    },
    @{
        Make="Apple"
        Model="iPhone 17 Pro Max"
        Lens="iPhone 17 Pro Max Main Camera"
    },
    @{
        Make="Samsung"
        Model="Galaxy S24 Ultra"
        Lens="Samsung Galaxy S24 Ultra Main Camera"
    },
    @{
        Make="Huawei"
        Model="Pura 70 Ultra"
        Lens="Huawei Pura 70 Ultra Main Camera"
    },
    @{
        Make="Huawei"
        Model="Mate 70 Pro"
        Lens="Huawei Mate 70 Pro Main Camera"
    },
    @{
        Make="Huawei"
        Model="Mate X6"
        Lens="Huawei Mate X6 Main Camera"
    },
    @{
        Make="Xiaomi"
        Model="Xiaomi 15 Ultra"
        Lens="Xiaomi 15 Ultra Main Camera"
    },
    @{
        Make="Xiaomi"
        Model="Xiaomi 15"
        Lens="Xiaomi 15 Main Camera"
    },
    @{
        Make="Redmi"
        Model="Redmi K80 Pro"
        Lens="Redmi K80 Pro Main Camera"
    },
    @{
        Make="Redmi"
        Model="Redmi Turbo 4 Pro"
        Lens="Redmi Turbo 4 Pro Main Camera"
    },
    @{
        Make="Honor"
        Model="Magic7 Pro"
        Lens="Honor Magic7 Pro Main Camera"
    },
    @{
        Make="Honor"
        Model="Magic V3"
        Lens="Honor Magic V3 Main Camera"
    },
    @{
        Make="OPPO"
        Model="Find X8 Pro"
        Lens="OPPO Find X8 Pro Main Camera"
    },
    @{
        Make="OPPO"
        Model="Find N5"
        Lens="OPPO Find N5 Main Camera"
    },
    @{
        Make="OPPO"
        Model="Reno13 Pro"
        Lens="OPPO Reno13 Pro Main Camera"
    },
    @{
        Make="vivo"
        Model="X200 Pro"
        Lens="vivo X200 Pro Main Camera"
    },
    @{
        Make="vivo"
        Model="X200 Ultra"
        Lens="vivo X200 Ultra Main Camera"
    },
    @{
        Make="vivo"
        Model="S20 Pro"
        Lens="vivo S20 Pro Main Camera"
    },
    @{
        Make="OnePlus"
        Model="OnePlus 13"
        Lens="OnePlus 13 Main Camera"
    },
    @{
        Make="OnePlus"
        Model="OnePlus Ace 5 Pro"
        Lens="OnePlus Ace 5 Pro Main Camera"
    },
    @{
        Make="realme"
        Model="GT 7 Pro"
        Lens="realme GT 7 Pro Main Camera"
    },
    @{
        Make="nubia"
        Model="Z70 Ultra"
        Lens="nubia Z70 Ultra Main Camera"
    },
    @{
        Make="Meizu"
        Model="Meizu 21 Pro"
        Lens="Meizu 21 Pro Main Camera"
    }
)



Get-ChildItem $WatermarkRemoved -File | ForEach-Object {


    $phone=$phones | Get-Random


    $time=(Get-Date).AddMinutes(
        -(Get-Random -Minimum 10 -Maximum 10000)
    )


    $out="$Output\$($_.BaseName).jpg"



    Write-Host "处理:" $_.Name



    #
    # 重新JPEG编码
    #
    # -strip `

    $quality = Get-Random -Minimum 96 -Maximum 100

    magick $_.FullName `
    -profile $ICC `
    -quality $quality `
    $out



    #
    # 写EXIF
    #

    $dateString = $time.ToString("yyyy:MM:dd HH:mm:ss")


    & $Exif `
        "-overwrite_original" `
        "-Make=$($phone.Make)" `
        "-Model=$($phone.Model)" `
        "-LensMake=$($phone.Make)" `
        "-LensModel=$($phone.Lens)" `
        "-DateTimeOriginal=$dateString" `
        "-CreateDate=$dateString" `
        "-FNumber=1.78" `
        "-ExposureTime=1/120" `
        "-ISO=100" `
        "-FocalLength=24 mm" `
        "-Flash=Off, Did not fire" `
        "-Software=iOS Camera" `
        "$out"


}



Write-Host ""
Write-Host "=============================="
Write-Host "完成!"
Write-Host "输出目录:"
Write-Host $Output
Write-Host "=============================="
