cuda_tile.module @m {
  entry @flash_attn_bf16(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f64>>, %arg4: tile<f32>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
    %2 = make_tensor_view %1, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
    %12 = constant <f32: -Infinity> : tile<32x1xf32>
    %13 = constant <f32: 0.0> : tile<32x1xf32>
    %14 = constant <f32: 0.0> : tile<32x32xf32>
    %15 = constant <i32: 0> : tile<i32>
    %16 = constant <i32: 2> : tile<i32>
    %17 = constant <i32: 1> : tile<i32>
    %18, %19, %20, %21 = for %22 in (%15 to %16, step %17) : tile<i32> iter_values(%23 = %12, %24 = %13, %25 = %14, %26 = %11) -> (tile<32x1xf32>, tile<32x1xf32>, tile<32x32xf32>, token) {
      %27 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %28 = make_tensor_view %27, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
      %29 = make_partition_view %28 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
      %30, %31 = load_view_tko weak %29[%22, %8] token=%26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
      %32 = permute %30 [1, 0] : tile<32x32xbf16> -> tile<32x32xbf16>
      %33 = constant <f32: 0.0> : tile<32x32xf32>
      %34 = mmaf %10, %32, %33 : tile<32x32xbf16>, tile<32x32xbf16>, tile<32x32xf32>
      %35 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
      %36 = broadcast %35 : tile<1x1xf32> -> tile<32x32xf32>
      %37 = mulf %34, %36 rounding<nearest_even> : tile<32x32xf32>
      %38 = reduce %37 dim=1 identities=[-Infinity : f32] : tile<32x32xf32> -> tile<32xf32> (%39: tile<f32>, %40: tile<f32>) {
        %41 = maxf %39, %40 : tile<f32>
        yield %41 : tile<f32>
      }
      %42 = reshape %38 : tile<32xf32> -> tile<32x1xf32>
      %43 = maxf %23, %42 : tile<32x1xf32>
      %44 = broadcast %43 : tile<32x1xf32> -> tile<32x32xf32>
      %45 = subf %37, %44 rounding<nearest_even> : tile<32x32xf32>
      %46 = exp %45 : tile<32x32xf32>
      %47 = subf %23, %43 rounding<nearest_even> : tile<32x1xf32>
      %48 = exp %47 : tile<32x1xf32>
      %49 = mulf %24, %48 rounding<nearest_even> : tile<32x1xf32>
      %50 = reduce %46 dim=1 identities=[0.0 : f32] : tile<32x32xf32> -> tile<32xf32> (%51: tile<f32>, %52: tile<f32>) {
        %53 = addf %51, %52 rounding<nearest_even> : tile<f32>
        yield %53 : tile<f32>
      }
      %54 = reshape %50 : tile<32xf32> -> tile<32x1xf32>
      %55 = addf %49, %54 rounding<nearest_even> : tile<32x1xf32>
      %56 = ftof %46 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xbf16>
      %57 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
      %58 = make_tensor_view %57, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
      %59 = make_partition_view %58 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
      %60, %61 = load_view_tko weak %59[%22, %8] token=%31 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
      %62 = broadcast %48 : tile<32x1xf32> -> tile<32x32xf32>
      %63 = mulf %25, %62 rounding<nearest_even> : tile<32x32xf32>
      %64 = mmaf %56, %60, %63 : tile<32x32xbf16>, tile<32x32xbf16>, tile<32x32xf32>
      continue %43, %55, %64, %61 : tile<32x1xf32>, tile<32x1xf32>, tile<32x32xf32>, token
    }
    %65 = broadcast %19 : tile<32x1xf32> -> tile<32x32xf32>
    %66 = divf %20, %65 rounding<nearest_even> : tile<32x32xf32>
    %67 = ftof %66 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xf64>
    %68 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %69 = make_tensor_view %68, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %70 = make_partition_view %69 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %71 = store_view_tko weak %67, %70[%4, %8] token=%21 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
