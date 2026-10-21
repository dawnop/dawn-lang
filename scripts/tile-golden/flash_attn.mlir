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
    %18, %19, %20 = for %21 in (%15 to %16, step %17) : tile<i32> iter_values(%22 = %12, %23 = %13, %24 = %14) -> (tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>) {
      %25 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %26 = make_tensor_view %25, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %27 = make_partition_view %26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %28, %29 = load_view_tko weak %27[%21, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %30 = permute %28 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %31 = constant <f64: 0.0> : tile<32x32xf64>
      %32 = mmaf %10, %30, %31 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      %33 = reshape %arg4 : tile<f64> -> tile<1x1xf64>
      %34 = broadcast %33 : tile<1x1xf64> -> tile<32x32xf64>
      %35 = mulf %32, %34 rounding<nearest_even> : tile<32x32xf64>
      %36 = reduce %35 dim=1 identities=[-Infinity : f64] : tile<32x32xf64> -> tile<32xf64> (%37: tile<f64>, %38: tile<f64>) {
        %39 = maxf %37, %38 : tile<f64>
        yield %39 : tile<f64>
      }
      %40 = reshape %36 : tile<32xf64> -> tile<32x1xf64>
      %41 = maxf %22, %40 : tile<32x1xf64>
      %42 = broadcast %41 : tile<32x1xf64> -> tile<32x32xf64>
      %43 = subf %35, %42 rounding<nearest_even> : tile<32x32xf64>
      %44 = exp %43 : tile<32x32xf64>
      %45 = subf %22, %41 rounding<nearest_even> : tile<32x1xf64>
      %46 = exp %45 : tile<32x1xf64>
      %47 = mulf %23, %46 rounding<nearest_even> : tile<32x1xf64>
      %48 = reduce %44 dim=1 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%49: tile<f64>, %50: tile<f64>) {
        %51 = addf %49, %50 rounding<nearest_even> : tile<f64>
        yield %51 : tile<f64>
      }
      %52 = reshape %48 : tile<32xf64> -> tile<32x1xf64>
      %53 = addf %47, %52 rounding<nearest_even> : tile<32x1xf64>
      %54 = assume div_by<16>, %arg2 : tile<ptr<f64>>
      %55 = make_tensor_view %54, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %56 = make_partition_view %55 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %57, %58 = load_view_tko weak %56[%21, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %59 = broadcast %46 : tile<32x1xf64> -> tile<32x32xf64>
      %60 = mulf %24, %59 rounding<nearest_even> : tile<32x32xf64>
      %61 = mmaf %44, %57, %60 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %41, %53, %61 : tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>
    }
    %62 = broadcast %19 : tile<32x1xf64> -> tile<32x32xf64>
    %63 = divf %20, %62 rounding<nearest_even> : tile<32x32xf64>
    %64 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %65 = make_tensor_view %64, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %66 = make_partition_view %65 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %67 = store_view_tko weak %63, %66[%4, %8] token=%0 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
