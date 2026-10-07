cuda_tile.module @m {
  entry @flash_attn(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<f64>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %12 = constant <f64: -Infinity> : tile<32x1xf64>
    %13 = constant <f64: 0.0> : tile<32x1xf64>
    %14 = constant <f64: 0.0> : tile<32x32xf64>
    %15 = constant <i32: 0> : tile<i32>
    %16 = constant <i32: 2> : tile<i32>
    %17 = constant <i32: 1> : tile<i32>
    %18, %19, %20, %21 = for %22 in (%15 to %16, step %17) : tile<i32> iter_values(%23 = %12, %24 = %13, %25 = %14, %26 = %11) -> (tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>, token) {
      %27 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %28 = make_tensor_view %27, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %29 = make_partition_view %28 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %30, %31 = load_view_tko weak %29[%22, %8] token=%26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %32 = permute %30 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %33 = constant <f64: 0.0> : tile<32x32xf64>
      %34 = mmaf %10, %32, %33 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      %35 = reshape %arg4 : tile<f64> -> tile<1x1xf64>
      %36 = broadcast %35 : tile<1x1xf64> -> tile<32x32xf64>
      %37 = mulf %34, %36 rounding<nearest_even> : tile<32x32xf64>
      %38 = reduce %37 dim=1 identities=[-Infinity : f64] : tile<32x32xf64> -> tile<32xf64> (%39: tile<f64>, %40: tile<f64>) {
        %41 = maxf %39, %40 : tile<f64>
        yield %41 : tile<f64>
      }
      %42 = reshape %38 : tile<32xf64> -> tile<32x1xf64>
      %43 = maxf %23, %42 : tile<32x1xf64>
      %44 = broadcast %43 : tile<32x1xf64> -> tile<32x32xf64>
      %45 = subf %37, %44 rounding<nearest_even> : tile<32x32xf64>
      %46 = exp %45 : tile<32x32xf64>
      %47 = subf %23, %43 rounding<nearest_even> : tile<32x1xf64>
      %48 = exp %47 : tile<32x1xf64>
      %49 = mulf %24, %48 rounding<nearest_even> : tile<32x1xf64>
      %50 = reduce %46 dim=1 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%51: tile<f64>, %52: tile<f64>) {
        %53 = addf %51, %52 rounding<nearest_even> : tile<f64>
        yield %53 : tile<f64>
      }
      %54 = reshape %50 : tile<32xf64> -> tile<32x1xf64>
      %55 = addf %49, %54 rounding<nearest_even> : tile<32x1xf64>
      %56 = assume div_by<16>, %arg2 : tile<ptr<f64>>
      %57 = make_tensor_view %56, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %58 = make_partition_view %57 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %59, %60 = load_view_tko weak %58[%22, %8] token=%31 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %61 = broadcast %48 : tile<32x1xf64> -> tile<32x32xf64>
      %62 = mulf %25, %61 rounding<nearest_even> : tile<32x32xf64>
      %63 = mmaf %46, %59, %62 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %43, %55, %63, %60 : tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>, token
    }
    %64 = broadcast %19 : tile<32x1xf64> -> tile<32x32xf64>
    %65 = divf %20, %64 rounding<nearest_even> : tile<32x32xf64>
    %66 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %67 = make_tensor_view %66, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %68 = make_partition_view %67 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %69 = store_view_tko weak %65, %68[%4, %8] token=%21 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
