cuda_tile.module @m {
  entry @flash_attn_bf16(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f64>>) {
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
      %35 = constant <f32: 0.17677669529663687> : tile<32x32xf32>
      %36 = mulf %34, %35 rounding<nearest_even> : tile<32x32xf32>
      %37 = reduce %36 dim=1 identities=[-Infinity : f32] : tile<32x32xf32> -> tile<32xf32> (%38: tile<f32>, %39: tile<f32>) {
        %40 = maxf %38, %39 : tile<f32>
        yield %40 : tile<f32>
      }
      %41 = reshape %37 : tile<32xf32> -> tile<32x1xf32>
      %42 = maxf %23, %41 : tile<32x1xf32>
      %43 = broadcast %42 : tile<32x1xf32> -> tile<32x32xf32>
      %44 = subf %36, %43 rounding<nearest_even> : tile<32x32xf32>
      %45 = exp %44 : tile<32x32xf32>
      %46 = subf %23, %42 rounding<nearest_even> : tile<32x1xf32>
      %47 = exp %46 : tile<32x1xf32>
      %48 = mulf %24, %47 rounding<nearest_even> : tile<32x1xf32>
      %49 = reduce %45 dim=1 identities=[0.0 : f32] : tile<32x32xf32> -> tile<32xf32> (%50: tile<f32>, %51: tile<f32>) {
        %52 = addf %50, %51 rounding<nearest_even> : tile<f32>
        yield %52 : tile<f32>
      }
      %53 = reshape %49 : tile<32xf32> -> tile<32x1xf32>
      %54 = addf %48, %53 rounding<nearest_even> : tile<32x1xf32>
      %55 = ftof %45 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xbf16>
      %56 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
      %57 = make_tensor_view %56, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
      %58 = make_partition_view %57 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
      %59, %60 = load_view_tko weak %58[%22, %8] token=%31 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
      %61 = broadcast %47 : tile<32x1xf32> -> tile<32x32xf32>
      %62 = mulf %25, %61 rounding<nearest_even> : tile<32x32xf32>
      %63 = mmaf %55, %59, %62 : tile<32x32xbf16>, tile<32x32xbf16>, tile<32x32xf32>
      continue %42, %54, %63, %60 : tile<32x1xf32>, tile<32x1xf32>, tile<32x32xf32>, token
    }
    %64 = broadcast %19 : tile<32x1xf32> -> tile<32x32xf32>
    %65 = divf %20, %64 rounding<nearest_even> : tile<32x32xf32>
    %66 = ftof %65 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xf64>
    %67 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %68 = make_tensor_view %67, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %69 = make_partition_view %68 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %70 = store_view_tko weak %66, %69[%4, %8] token=%21 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
