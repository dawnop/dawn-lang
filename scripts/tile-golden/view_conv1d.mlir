cuda_tile.module @m {
  entry @view_conv1d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %3 = offset %2, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %4 = make_tensor_view %3, shape = [260], strides = [1] : tensor_view<260xf64, strides=[1]>
    %5 = make_strided_view %4 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>
    %6 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %7 = offset %6, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %9 = make_strided_view %8 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %5[%10] token=%0 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %15, %16 = load_view_tko weak %9[%1] token=%0 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %17 = mulf %13, %15 rounding<nearest_even> : tile<4xf64>
    %18 = reduce %17 dim=0 identities=[0.0 : f64] : tile<4xf64> -> tile<f64> (%19: tile<f64>, %20: tile<f64>) {
      %21 = addf %19, %20 rounding<nearest_even> : tile<f64>
      yield %21 : tile<f64>
    }
    %22 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [257], strides = [1] : tensor_view<257xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(1), padding_value = zero, tensor_view<257xf64, strides=[1]>, dim_map=[0]>
    %25, %26, %27 = get_tile_block_id : tile<i32>
    %28 = reshape %18 : tile<f64> -> tile<1xf64>
    %29 = broadcast %28 : tile<1xf64> -> tile<1xf64>
    %30 = store_view_tko weak %29, %24[%25] token=%0 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<257xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
