cuda_tile.module @m {
  entry @flash_bf16_tail_sm100_d64(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>) optimization_hints=<sm_100 = {num_cta_in_cga = 2, occupancy = 2}> {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
    %2 = make_tensor_view %1, shape = [2, 255, 64], strides = [16320, 64, 1] : tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x256x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %3[%6, %7, %11] token=%0 : partition_view<tile=(1x256x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x256x64xbf16>, token
    %15 = reshape %13 : tile<1x256x64xbf16> -> tile<256x64xbf16>
    %16 = constant <f32: -Infinity> : tile<256x1xf32>
    %17 = constant <f32: 0.0> : tile<256x1xf32>
    %18 = constant <f32: 0.0> : tile<256x64xf32>
    %19 = constant <i32: 0> : tile<i32>
    %20 = constant <i32: 4> : tile<i32>
    %21 = constant <i32: 1> : tile<i32>
    %22, %23, %24 = for %25 in (%19 to %20, step %21) : tile<i32> iter_values(%26 = %16, %27 = %17, %28 = %18) -> (tile<256x1xf32>, tile<256x1xf32>, tile<256x64xf32>) {
      %29 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %30 = make_tensor_view %29, shape = [2, 255, 64], strides = [16320, 64, 1] : tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>
      %31 = make_partition_view %30 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>
      %32, %33 = load_view_tko weak %31[%6, %25, %11] token=%0 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x64x64xbf16>, token
      %34 = reshape %32 : tile<1x64x64xbf16> -> tile<64x64xbf16>
      %35 = permute %34 [1, 0] : tile<64x64xbf16> -> tile<64x64xbf16>
      %36 = constant <f32: 0.0> : tile<256x64xf32>
      %37 = mmaf %15, %35, %36 : tile<256x64xbf16>, tile<64x64xbf16>, tile<256x64xf32>
      %38 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
      %39 = broadcast %38 : tile<1x1xf32> -> tile<256x64xf32>
      %40 = mulf %37, %39 rounding<nearest_even> : tile<256x64xf32>
      %41 = constant <i32: 64> : tile<i32>
      %42 = muli %25, %41 : tile<i32>
      %43 = reshape %42 : tile<i32> -> tile<1x1xi32>
      %44 = broadcast %43 : tile<1x1xi32> -> tile<256x64xi32>
      %45 = iota : tile<256xi32>
      %46 = reshape %45 : tile<256xi32> -> tile<256x1xi32>
      %47 = broadcast %46 : tile<256x1xi32> -> tile<256x64xi32>
      %48 = constant <i32: 0> : tile<256x64xi32>
      %49 = muli %47, %48 : tile<256x64xi32>
      %50 = addi %44, %49 : tile<256x64xi32>
      %51 = iota : tile<64xi32>
      %52 = reshape %51 : tile<64xi32> -> tile<1x64xi32>
      %53 = broadcast %52 : tile<1x64xi32> -> tile<256x64xi32>
      %54 = addi %50, %53 : tile<256x64xi32>
      %55 = constant <i32: 255> : tile<256x64xi32>
      %56 = cmpi less_than %54, %55, signed : tile<256x64xi32> -> tile<256x64xi1>
      %57 = constant <f32: -Infinity> : tile<256x64xf32>
      %58 = select %56, %40, %57 : tile<256x64xi1>, tile<256x64xf32>
      %59 = reduce %58 dim=1 identities=[-Infinity : f32] : tile<256x64xf32> -> tile<256xf32> (%60: tile<f32>, %61: tile<f32>) {
        %62 = maxf %60, %61 : tile<f32>
        yield %62 : tile<f32>
      }
      %63 = reshape %59 : tile<256xf32> -> tile<256x1xf32>
      %64 = maxf %26, %63 : tile<256x1xf32>
      %65 = broadcast %64 : tile<256x1xf32> -> tile<256x64xf32>
      %66 = subf %58, %65 rounding<nearest_even> : tile<256x64xf32>
      %67 = exp2 %66 flush_to_zero : tile<256x64xf32>
      %68 = subf %26, %64 rounding<nearest_even> : tile<256x1xf32>
      %69 = exp2 %68 flush_to_zero : tile<256x1xf32>
      %70 = mulf %27, %69 rounding<nearest_even> : tile<256x1xf32>
      %71 = reduce %67 dim=1 identities=[0.0 : f32] : tile<256x64xf32> -> tile<256xf32> (%72: tile<f32>, %73: tile<f32>) {
        %74 = addf %72, %73 rounding<nearest_even> : tile<f32>
        yield %74 : tile<f32>
      }
      %75 = reshape %71 : tile<256xf32> -> tile<256x1xf32>
      %76 = addf %70, %75 rounding<nearest_even> : tile<256x1xf32>
      %77 = ftof %67 rounding<nearest_even> : tile<256x64xf32> -> tile<256x64xbf16>
      %78 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
      %79 = make_tensor_view %78, shape = [2, 255, 64], strides = [16320, 64, 1] : tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>
      %80 = make_partition_view %79 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>
      %81, %82 = load_view_tko weak %80[%6, %25, %11] token=%0 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x255x64xbf16, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x64x64xbf16>, token
      %83 = reshape %81 : tile<1x64x64xbf16> -> tile<64x64xbf16>
      %84 = broadcast %69 : tile<256x1xf32> -> tile<256x64xf32>
      %85 = mulf %28, %84 rounding<nearest_even> : tile<256x64xf32>
      %86 = mmaf %77, %83, %85 : tile<256x64xbf16>, tile<64x64xbf16>, tile<256x64xf32>
      continue %64, %76, %86 : tile<256x1xf32>, tile<256x1xf32>, tile<256x64xf32>
    }
    %87 = broadcast %23 : tile<256x1xf32> -> tile<256x64xf32>
    %88 = divf %24, %87 rounding<approx> flush_to_zero : tile<256x64xf32>
    %89 = reshape %88 : tile<256x64xf32> -> tile<1x256x64xf32>
    %90 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %91 = make_tensor_view %90, shape = [2, 255, 64], strides = [16320, 64, 1] : tensor_view<2x255x64xf32, strides=[16320, 64, 1]>
    %92 = make_partition_view %91 : partition_view<tile=(1x256x64), padding_value = zero, tensor_view<2x255x64xf32, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>
    %93 = store_view_tko weak %89, %92[%6, %7, %11] token=%0 : tile<1x256x64xf32>, partition_view<tile=(1x256x64), padding_value = zero, tensor_view<2x255x64xf32, strides=[16320, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
