cuda_tile.module @m {
  entry @llama_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 2> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9 = addi %5, %6 : tile<i32>
    %10 = constant <i32: 2048> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %13 = broadcast %12 : tile<1x1xi32> -> tile<64x32xi32>
    %14 = iota : tile<64xi32>
    %15 = reshape %14 : tile<64xi32> -> tile<64x1xi32>
    %16 = broadcast %15 : tile<64x1xi32> -> tile<64x32xi32>
    %17 = constant <i32: 32> : tile<64x32xi32>
    %18 = muli %16, %17 : tile<64x32xi32>
    %19 = addi %13, %18 : tile<64x32xi32>
    %20 = iota : tile<32xi32>
    %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
    %22 = broadcast %21 : tile<1x32xi32> -> tile<64x32xi32>
    %23 = addi %19, %22 : tile<64x32xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %26 = offset %25, %23 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %27, %28 = load_ptr_tko weak %26 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [128, 32], strides = [32, 1] : tensor_view<128x32xf64, strides=[32, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38, %39 = load_view_tko weak %31[%34, %36] token=%28 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %40 = permute %38 [1, 0] : tile<64x32xf64> -> tile<32x64xf64>
    %41 = constant <f64: 0.0> : tile<64x64xf64>
    %42 = mmaf %27, %40, %41 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %43 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %44 = mulf %42, %43 rounding<nearest_even> : tile<64x64xf64>
    %45 = constant <i32: 0> : tile<i32>
    %46 = reshape %45 : tile<i32> -> tile<1x1xi32>
    %47 = broadcast %46 : tile<1x1xi32> -> tile<64x64xi32>
    %48 = iota : tile<64xi32>
    %49 = reshape %48 : tile<64xi32> -> tile<64x1xi32>
    %50 = broadcast %49 : tile<64x1xi32> -> tile<64x64xi32>
    %51 = addi %47, %50 : tile<64x64xi32>
    %52 = iota : tile<64xi32>
    %53 = reshape %52 : tile<64xi32> -> tile<1x64xi32>
    %54 = broadcast %53 : tile<1x64xi32> -> tile<64x64xi32>
    %55 = constant <i32: 0> : tile<64x64xi32>
    %56 = muli %54, %55 : tile<64x64xi32>
    %57 = addi %51, %56 : tile<64x64xi32>
    %58 = constant <i32: 0> : tile<i32>
    %59 = reshape %58 : tile<i32> -> tile<1x1xi32>
    %60 = broadcast %59 : tile<1x1xi32> -> tile<64x64xi32>
    %61 = iota : tile<64xi32>
    %62 = reshape %61 : tile<64xi32> -> tile<64x1xi32>
    %63 = broadcast %62 : tile<64x1xi32> -> tile<64x64xi32>
    %64 = constant <i32: 0> : tile<64x64xi32>
    %65 = muli %63, %64 : tile<64x64xi32>
    %66 = addi %60, %65 : tile<64x64xi32>
    %67 = iota : tile<64xi32>
    %68 = reshape %67 : tile<64xi32> -> tile<1x64xi32>
    %69 = broadcast %68 : tile<1x64xi32> -> tile<64x64xi32>
    %70 = addi %66, %69 : tile<64x64xi32>
    %71 = cmpi greater_than_or_equal %57, %70, signed : tile<64x64xi32> -> tile<64x64xi1>
    %72 = constant <f64: -Infinity> : tile<64x64xf64>
    %73 = select %71, %44, %72 : tile<64x64xi1>, tile<64x64xf64>
    %74 = reshape %73 : tile<64x64xf64> -> tile<1x64x64xf64>
    %75 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %76 = make_tensor_view %75, shape = [2, 128, 64], strides = [8192, 64, 1] : tensor_view<2x128x64xf64, strides=[8192, 64, 1]>
    %77 = make_partition_view %76 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x128x64xf64, strides=[8192, 64, 1]>, dim_map=[0, 1, 2]>
    %78, %79, %80 = get_tile_block_id : tile<i32>
    %81 = store_view_tko weak %74, %77[%34, %78, %36] token=%39 : tile<1x64x64xf64>, partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x128x64xf64, strides=[8192, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
