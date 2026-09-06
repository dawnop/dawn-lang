cuda_tile.module @m {
  entry @view_conv1d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = offset %arg0, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %6 = make_tensor_view %5, shape = [260], strides = [1] : tensor_view<260xf64, strides=[1]>
    %7 = make_strided_view %6 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>
    %8 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %9 = make_tensor_view %8, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %10 = make_strided_view %9 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %11, %12 = load_view_tko weak %7[%2] token=%0 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %13, %14 = load_view_tko weak %10[%1] token=%12 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %15 = mulf %11, %13 rounding<nearest_even> : tile<4xf64>
    %16 = constant <i32: 1> : tile<i32>
    %17 = muli %2, %16 : tile<i32>
    %18 = reduce %15 dim=0 identities=[0.0 : f64] : tile<4xf64> -> tile<f64> (%19: tile<f64>, %20: tile<f64>) {
      %21 = addf %19, %20 rounding<nearest_even> : tile<f64>
      yield %21 : tile<f64>
    }
    %22 = reshape %18 : tile<f64> -> tile<1xf64>
    %23 = broadcast %22 : tile<1xf64> -> tile<1xf64>
    %24 = reshape %17 : tile<i32> -> tile<1xi32>
    %25 = broadcast %24 : tile<1xi32> -> tile<1xi32>
    %26 = iota : tile<1xi32>
    %27 = addi %25, %26 : tile<1xi32>
    %28 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %29 = broadcast %28 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %30 = offset %29, %27 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %31 = store_ptr_tko weak %30, %23 token=%14 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
