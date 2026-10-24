cuda_tile.module @m {
  entry @flash_bf16_sm90_d64(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>) optimization_hints=<sm_90 = {occupancy = 2}> {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
    %2 = make_tensor_view %1, shape = [1, 256, 64], strides = [16384, 64, 1] : tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %3[%6, %7, %11] token=%0 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x64x64xbf16>, token
    %15 = reshape %13 : tile<1x64x64xbf16> -> tile<64x64xbf16>
    %16 = constant <f32: -Infinity> : tile<64x1xf32>
    %17 = constant <f32: 0.0> : tile<64x1xf32>
    %18 = constant <f32: 0.0> : tile<64x64xf32>
    %19 = constant <i32: 0> : tile<i32>
    %20 = constant <i32: 2> : tile<i32>
    %21 = constant <i32: 1> : tile<i32>
    %22, %23, %24 = for %25 in (%19 to %20, step %21) : tile<i32> iter_values(%26 = %16, %27 = %17, %28 = %18) -> (tile<64x1xf32>, tile<64x1xf32>, tile<64x64xf32>) {
      %29 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %30 = make_tensor_view %29, shape = [1, 256, 64], strides = [16384, 64, 1] : tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>
      %31 = make_partition_view %30 : partition_view<tile=(1x128x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>
      %32, %33 = load_view_tko weak %31[%6, %25, %11] token=%0 : partition_view<tile=(1x128x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x128x64xbf16>, token
      %34 = reshape %32 : tile<1x128x64xbf16> -> tile<128x64xbf16>
      %35 = permute %34 [1, 0] : tile<128x64xbf16> -> tile<64x128xbf16>
      %36 = constant <f32: 0.0> : tile<64x128xf32>
      %37 = mmaf %15, %35, %36 : tile<64x64xbf16>, tile<64x128xbf16>, tile<64x128xf32>
      %38 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
      %39 = broadcast %38 : tile<1x1xf32> -> tile<64x128xf32>
      %40 = mulf %37, %39 rounding<nearest_even> : tile<64x128xf32>
      %41 = reduce %40 dim=1 identities=[-Infinity : f32] : tile<64x128xf32> -> tile<64xf32> (%42: tile<f32>, %43: tile<f32>) {
        %44 = maxf %42, %43 : tile<f32>
        yield %44 : tile<f32>
      }
      %45 = reshape %41 : tile<64xf32> -> tile<64x1xf32>
      %46 = maxf %26, %45 : tile<64x1xf32>
      %47 = broadcast %46 : tile<64x1xf32> -> tile<64x128xf32>
      %48 = subf %40, %47 rounding<nearest_even> : tile<64x128xf32>
      %49 = exp2 %48 flush_to_zero : tile<64x128xf32>
      %50 = subf %26, %46 rounding<nearest_even> : tile<64x1xf32>
      %51 = exp2 %50 flush_to_zero : tile<64x1xf32>
      %52 = mulf %27, %51 rounding<nearest_even> : tile<64x1xf32>
      %53 = reduce %49 dim=1 identities=[0.0 : f32] : tile<64x128xf32> -> tile<64xf32> (%54: tile<f32>, %55: tile<f32>) {
        %56 = addf %54, %55 rounding<nearest_even> : tile<f32>
        yield %56 : tile<f32>
      }
      %57 = reshape %53 : tile<64xf32> -> tile<64x1xf32>
      %58 = addf %52, %57 rounding<nearest_even> : tile<64x1xf32>
      %59 = ftof %49 rounding<nearest_even> : tile<64x128xf32> -> tile<64x128xbf16>
      %60 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
      %61 = make_tensor_view %60, shape = [1, 256, 64], strides = [16384, 64, 1] : tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>
      %62 = make_partition_view %61 : partition_view<tile=(1x128x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>
      %63, %64 = load_view_tko weak %62[%6, %25, %11] token=%0 : partition_view<tile=(1x128x64), padding_value = zero, tensor_view<1x256x64xbf16, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x128x64xbf16>, token
      %65 = reshape %63 : tile<1x128x64xbf16> -> tile<128x64xbf16>
      %66 = broadcast %51 : tile<64x1xf32> -> tile<64x64xf32>
      %67 = mulf %28, %66 rounding<nearest_even> : tile<64x64xf32>
      %68 = mmaf %59, %65, %67 : tile<64x128xbf16>, tile<128x64xbf16>, tile<64x64xf32>
      continue %46, %58, %68 : tile<64x1xf32>, tile<64x1xf32>, tile<64x64xf32>
    }
    %69 = broadcast %23 : tile<64x1xf32> -> tile<64x64xf32>
    %70 = divf %24, %69 rounding<approx> flush_to_zero : tile<64x64xf32>
    %71 = reshape %70 : tile<64x64xf32> -> tile<1x64x64xf32>
    %72 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %73 = make_tensor_view %72, shape = [1, 256, 64], strides = [16384, 64, 1] : tensor_view<1x256x64xf32, strides=[16384, 64, 1]>
    %74 = make_partition_view %73 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<1x256x64xf32, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>
    %75 = store_view_tko weak %71, %74[%6, %7, %11] token=%0 : tile<1x64x64xf32>, partition_view<tile=(1x64x64), padding_value = zero, tensor_view<1x256x64xf32, strides=[16384, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
