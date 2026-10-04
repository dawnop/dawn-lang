cuda_tile.module @m {
  entry @mha_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 32> : tile<i32>
    %8 = muli %6, %7 : tile<i32>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 4096> : tile<i32>
    %13 = muli %11, %12 : tile<i32>
    %14 = constant <i32: 2048> : tile<i32>
    %15 = muli %1, %14 : tile<i32>
    %16 = addi %13, %15 : tile<i32>
    %17 = constant <f64: 0.0> : tile<32x32xf64>
    %18 = constant <i32: 0> : tile<i32>
    %19 = constant <i32: 2> : tile<i32>
    %20 = constant <i32: 1> : tile<i32>
    %21, %22 = for %23 in (%18 to %19, step %20) : tile<i32> iter_values(%24 = %17, %25 = %0) -> (tile<32x32xf64>, token) {
      %26 = constant <i32: 32> : tile<i32>
      %27 = muli %23, %26 : tile<i32>
      %28 = addi %16, %27 : tile<i32>
      %29 = reshape %28 : tile<i32> -> tile<1x1xi32>
      %30 = broadcast %29 : tile<1x1xi32> -> tile<32x32xi32>
      %31 = iota : tile<32xi32>
      %32 = reshape %31 : tile<32xi32> -> tile<32x1xi32>
      %33 = broadcast %32 : tile<32x1xi32> -> tile<32x32xi32>
      %34 = constant <i32: 64> : tile<32x32xi32>
      %35 = muli %33, %34 : tile<32x32xi32>
      %36 = addi %30, %35 : tile<32x32xi32>
      %37 = iota : tile<32xi32>
      %38 = reshape %37 : tile<32xi32> -> tile<1x32xi32>
      %39 = broadcast %38 : tile<1x32xi32> -> tile<32x32xi32>
      %40 = addi %36, %39 : tile<32x32xi32>
      %41 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %42 = broadcast %41 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %43 = offset %42, %40 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %44, %45 = load_ptr_tko weak %43 token=%25 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %46 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %47 = make_tensor_view %46, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %48 = make_partition_view %47 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %49, %50, %51 = get_tile_block_id : tile<i32>
      %52, %53 = load_view_tko weak %48[%23, %51] token=%45 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %54 = mmaf %44, %52, %24 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %54, %53 : tile<32x32xf64>, token
    }
    %55 = constant <i32: 2048> : tile<i32>
    %56 = muli %1, %55 : tile<i32>
    %57 = addi %56, %8 : tile<i32>
    %58 = reshape %57 : tile<i32> -> tile<1x1xi32>
    %59 = broadcast %58 : tile<1x1xi32> -> tile<32x32xi32>
    %60 = iota : tile<32xi32>
    %61 = reshape %60 : tile<32xi32> -> tile<32x1xi32>
    %62 = broadcast %61 : tile<32x1xi32> -> tile<32x32xi32>
    %63 = constant <i32: 64> : tile<32x32xi32>
    %64 = muli %62, %63 : tile<32x32xi32>
    %65 = addi %59, %64 : tile<32x32xi32>
    %66 = iota : tile<32xi32>
    %67 = reshape %66 : tile<32xi32> -> tile<1x32xi32>
    %68 = broadcast %67 : tile<1x32xi32> -> tile<32x32xi32>
    %69 = addi %65, %68 : tile<32x32xi32>
    %70 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %71 = broadcast %70 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %72 = offset %71, %69 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %73 = store_ptr_tko weak %72, %21 token=%22 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
