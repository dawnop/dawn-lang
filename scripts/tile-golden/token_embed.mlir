cuda_tile.module @m {
  entry @token_embed(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 8> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<8x16xi32>
    %8 = iota : tile<8xi32>
    %9 = reshape %8 : tile<8xi32> -> tile<8x1xi32>
    %10 = broadcast %9 : tile<8x1xi32> -> tile<8x16xi32>
    %11 = addi %7, %10 : tile<8x16xi32>
    %12 = iota : tile<16xi32>
    %13 = reshape %12 : tile<16xi32> -> tile<1x16xi32>
    %14 = broadcast %13 : tile<1x16xi32> -> tile<8x16xi32>
    %15 = constant <i32: 0> : tile<8x16xi32>
    %16 = muli %14, %15 : tile<8x16xi32>
    %17 = addi %11, %16 : tile<8x16xi32>
    %18 = reshape %arg0 : tile<ptr<i32>> -> tile<1x1xptr<i32>>
    %19 = broadcast %18 : tile<1x1xptr<i32>> -> tile<8x16xptr<i32>>
    %20 = offset %19, %17 : tile<8x16xptr<i32>>, tile<8x16xi32> -> tile<8x16xptr<i32>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<8x16xptr<i32>> -> tile<8x16xi32>, token
    %23 = constant <i32: 0> : tile<8x16xi32>
    %24 = cmpi greater_than_or_equal %21, %23, signed : tile<8x16xi32> -> tile<8x16xi1>
    %25 = constant <i32: 64> : tile<8x16xi32>
    %26 = cmpi less_than %21, %25, signed : tile<8x16xi32> -> tile<8x16xi1>
    %27 = constant <i1: 0> : tile<8x16xi1>
    %28 = select %24, %26, %27 : tile<8x16xi1>, tile<8x16xi1>
    %29 = constant <i32: 63> : tile<8x16xi32>
    %30 = andi %21, %29 : tile<8x16xi32>
    %31 = constant <i32: 16> : tile<8x16xi32>
    %32 = muli %30, %31 : tile<8x16xi32>
    %33 = constant <i32: 0> : tile<i32>
    %34 = reshape %33 : tile<i32> -> tile<1x1xi32>
    %35 = broadcast %34 : tile<1x1xi32> -> tile<8x16xi32>
    %36 = iota : tile<8xi32>
    %37 = reshape %36 : tile<8xi32> -> tile<8x1xi32>
    %38 = broadcast %37 : tile<8x1xi32> -> tile<8x16xi32>
    %39 = constant <i32: 0> : tile<8x16xi32>
    %40 = muli %38, %39 : tile<8x16xi32>
    %41 = addi %35, %40 : tile<8x16xi32>
    %42 = iota : tile<16xi32>
    %43 = reshape %42 : tile<16xi32> -> tile<1x16xi32>
    %44 = broadcast %43 : tile<1x16xi32> -> tile<8x16xi32>
    %45 = addi %41, %44 : tile<8x16xi32>
    %46 = addi %32, %45 : tile<8x16xi32>
    %47 = constant <f64: -777.0> : tile<8x16xf64>
    %48 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %49 = broadcast %48 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %50 = offset %49, %46 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %51, %52 = load_ptr_tko weak %50, %28, %47 token=%22 : tile<8x16xptr<f64>>, tile<8x16xi1>, tile<8x16xf64> -> tile<8x16xf64>, token
    %53, %54, %55 = get_num_tile_blocks : tile<i32>
    %56 = constant <i32: 8> : tile<i32>
    %57 = muli %53, %56 : tile<i32>
    %58 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %59 = make_tensor_view %58, shape = [%57, 16], strides = [16, 1] : tile<i32> -> tensor_view<?x16xf64, strides=[16, 1]>
    %60 = make_partition_view %59 : partition_view<tile=(8x16), padding_value = zero, tensor_view<?x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %61, %62, %63 = get_tile_block_id : tile<i32>
    %64, %65, %66 = get_tile_block_id : tile<i32>
    %67 = store_view_tko weak %51, %60[%61, %65] token=%52 : tile<8x16xf64>, partition_view<tile=(8x16), padding_value = zero, tensor_view<?x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
